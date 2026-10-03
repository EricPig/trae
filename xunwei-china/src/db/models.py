"""ORM 模型 —— 核心数据。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    Index,
    UniqueConstraint,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from pgvector.sqlalchemy import Vector

from src.config import get_settings


settings = get_settings()
VEC_DIM = settings.vector_dimension


class Base(DeclarativeBase):
    """ORM 基类。"""

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ============================================================================
# 地理 / 菜系参考数据（共享内核）
# ============================================================================


class GeoEntity(Base):
    """行政区划：省 → 市 → 区县 → 街道。"""

    __tablename__ = "geo_entity"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)  # province/city/district/street
    parent_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("geo_entity.id"))
    code: Mapped[Optional[str]] = mapped_column(String(20), unique=True)  # 行政区划代码
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)


class Cuisine(Base):
    """菜系（川菜、粤菜…）。"""

    __tablename__ = "cuisine"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("cuisine.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)


class Technique(Base):
    """烹饪技法（煎、炸、炒、炖…）。"""

    __tablename__ = "technique"

    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)


class Ingredient(Base):
    """食材。"""

    __tablename__ = "ingredient"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_allergen: Mapped[bool] = mapped_column(Boolean, default=False)
    allergen_type: Mapped[Optional[str]] = mapped_column(String(50))  # 花生/牛奶/海鲜…


# ============================================================================
# 数据源（每条菜品必须带来源 —— 基线清单 FF-DATA-01）
# ============================================================================


class DataSource(Base):
    """数据源 + 许可证。"""

    __tablename__ = "data_source"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    license_type: Mapped[str] = mapped_column(String(50), nullable=False)  # ODbL/CC0/proprietary/...
    url: Mapped[Optional[str]] = mapped_column(String(500))
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False)


# ============================================================================
# 核心：菜品（Dish）
# ============================================================================


class Dish(Base):
    """
    菜品实体。

    核心架构字段（准入/排序/展示）：
      - locality_level: native / localized / national_chain  —— 二维准入表第一维
      - cuisine_evidence_level: A / B / C / D  —— 二维准入表第二维
      - locality_score: 单标量排序得分（60/25/15 权重表计算）
      - admission_result: 准入判定结果
    """

    __tablename__ = "dish"

    # ---- 基础 ----
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    cuisine_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("cuisine.id"))
    geo_entity_id: Mapped[UUID] = mapped_column(ForeignKey("geo_entity.id"), nullable=False)
    establishment_year: Mapped[Optional[int]] = mapped_column(Integer)

    # ---- 核心架构字段（准入 + 排序）----
    locality_level: Mapped[str] = mapped_column(String(20), nullable=False)  # native/localized/national_chain
    cuisine_evidence_level: Mapped[str] = mapped_column(String(1), nullable=False)  # A/B/C/D
    locality_score: Mapped[float] = mapped_column(Float, nullable=False)
    admission_result: Mapped[str] = mapped_column(String(30), nullable=False)

    # ---- 过敏原 / 安全 ----
    common_allergens: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    allergen_info_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    # ---- 排序辅助（locality_score 组成）----
    years_factor: Mapped[float] = mapped_column(Float, default=0.0)
    cuisine_factor: Mapped[float] = mapped_column(Float, default=0.0)
    native_score: Mapped[float] = mapped_column(Float, default=0.0)

    # ---- 争议 / 多源 ----
    geo_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    geo_conflict_note: Mapped[Optional[str]] = mapped_column(Text)

    # ---- 数据源（必须标注）----
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[Optional[str]] = mapped_column(String(50))
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # ---- 向量化（RAG 用）----
    embedding: Mapped[Optional[Vector]] = mapped_column(Vector(VEC_DIM))

    # ---- 关系 ----
    cuisine: Mapped["Cuisine"] = relationship()
    geo_entity: Mapped["GeoEntity"] = relationship()

    # ---- 索引 ----
    __table_args__ = (
        Index("ix_dish_locality_score", "locality_score"),
        Index("ix_dish_admission", "admission_result"),
        Index("ix_dish_locality_level", "locality_level"),
        Index("ix_dish_geo_entity", "geo_entity_id"),
        Index("ix_dish_allergens", "common_allergens", postgresql_using="gin"),
    )


# ============================================================================
# 商户（只读集成 —— 不做商户评分）
# ============================================================================


class Merchant(Base):
    """商户点位数据。仅用于导航跳转，不做评分/排名。"""

    __tablename__ = "merchant"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geo_entity_id: Mapped[UUID] = mapped_column(ForeignKey("geo_entity.id"))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    navigation_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ============================================================================
# 用户画像（敏感数据 —— 注意脱敏）
# ============================================================================


class UserProfile(Base):
    """用户画像。"""

    __tablename__ = "user_profile"

    user_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 用户标识哈希
    dietary_restrictions: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)  # 忌口/过敏
    taste_preferences: Mapped[JSONB] = mapped_column(JSONB, default=dict)  # 口味偏好标签
    family_profile_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("family_profile.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FamilyProfile(Base):
    """家庭多人档案（多人合并口味）。"""

    __tablename__ = "family_profile"

    name: Mapped[str] = mapped_column(String(100))
    dietary_restrictions_merged: Mapped[List[str]] = mapped_column(ARRAY(String), default=list)
    taste_preferences_merged: Mapped[JSONB] = mapped_column(JSONB, default=dict)


class FavoriteList(Base):
    """收藏 / 清单。"""

    __tablename__ = "favorite_list"

    user_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # 清单锁定（去重）
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)


class FavoriteListItem(Base):
    """清单条目。"""

    __tablename__ = "favorite_list_item"

    list_id: Mapped[UUID] = mapped_column(ForeignKey("favorite_list.id"), nullable=False, index=True)
    dish_id: Mapped[UUID] = mapped_column(ForeignKey("dish.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ============================================================================
# 行为事件（埋点 —— 异步写入）
# ============================================================================


class BehaviorEvent(Base):
    """行为事件流。"""

    __tablename__ = "behavior_event"

    user_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[UUID]] = mapped_column(UUID)
    properties: Mapped[JSONB] = mapped_column(JSONB, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_behavior_user_time", "user_hash", "occurred_at"),
        Index("ix_behavior_event_time", "event_name", "occurred_at"),
    )
