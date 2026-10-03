"""ORM 模型 —— 核心数据。

PostgreSQL 生产、SQLite 开发/测试 —— dialect-aware 类型层（src/db/types.py）
自动适配，Python API 不变。
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    Date, DateTime, Float, Integer, String, Text, Boolean,
    Index, UniqueConstraint, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

try:
    from pgvector.sqlalchemy import Vector  # noqa: F401
    _VEC_AVAILABLE = True
except ImportError:
    _VEC_AVAILABLE = False

from src.config import get_settings
from src.db.types import ListType, JSONDictType, UUID_Type


settings = get_settings()
VEC_DIM = settings.vector_dimension


# ======================================================================
# Base
# ======================================================================


def _utcnow():
    """F2 fix: timezone-aware UTC —— 取代已 deprecate 的 datetime.utcnow()"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """ORM 基类。"""

    id: Mapped[object] = mapped_column(UUID_Type(), primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


# ============================================================================
# 地理 / 菜系参考数据
# ============================================================================


class GeoEntity(Base):
    __tablename__ = "geo_entity"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False)  # province/city/district/street
    parent_id: Mapped[Optional[object]] = mapped_column(ForeignKey("geo_entity.id"))
    code: Mapped[Optional[str]] = mapped_column(String(20), unique=True)
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)


class Cuisine(Base):
    __tablename__ = "cuisine"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    parent_id: Mapped[Optional[object]] = mapped_column(ForeignKey("cuisine.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)


class Technique(Base):
    __tablename__ = "technique"

    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)


class Ingredient(Base):
    __tablename__ = "ingredient"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_allergen: Mapped[bool] = mapped_column(Boolean, default=False)
    allergen_type: Mapped[Optional[str]] = mapped_column(String(50))


# ============================================================================
# 数据源（每条菜品必须带来源 —— FF-DATA-01）
# ============================================================================


class DataSource(Base):
    __tablename__ = "data_source"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    license_type: Mapped[str] = mapped_column(String(50), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False)


# ============================================================================
# 核心：菜品
# ============================================================================


class Dish(Base):
    """
    菜品实体。

    核心架构字段：
      - locality_level: native / localized / national_chain —— 二维准入第一维
      - cuisine_evidence_level: A / B / C / D —— 二维准入第二维
      - locality_score: 单标量排序得分（60/25/15 权重）
      - admission_result: 准入判定
    """

    __tablename__ = "dish"

    # ---- 基础 ----
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    cuisine_id: Mapped[Optional[object]] = mapped_column(ForeignKey("cuisine.id"))
    geo_entity_id: Mapped[object] = mapped_column(ForeignKey("geo_entity.id"), nullable=False)
    establishment_year: Mapped[Optional[int]] = mapped_column(Integer)

    # ---- 架构字段（准入 + 排序）----
    locality_level: Mapped[str] = mapped_column(String(20), nullable=False)
    cuisine_evidence_level: Mapped[str] = mapped_column(String(1), nullable=False)
    locality_score: Mapped[float] = mapped_column(Float, nullable=False)
    admission_result: Mapped[str] = mapped_column(String(30), nullable=False)

    # ---- 过敏原 / 安全 ----
    common_allergens: Mapped[List[str]] = mapped_column(ListType(String), default=list)
    allergen_info_complete: Mapped[bool] = mapped_column(Boolean, default=False)

    # ---- 排序辅助 ----
    years_factor: Mapped[float] = mapped_column(Float, default=0.0)
    cuisine_factor: Mapped[float] = mapped_column(Float, default=0.0)
    native_score: Mapped[float] = mapped_column(Float, default=0.0)

    # ---- 争议 ----
    geo_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    geo_conflict_note: Mapped[Optional[str]] = mapped_column(Text)

    # ---- 数据源（必须标注）----
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_version: Mapped[Optional[str]] = mapped_column(String(50))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # ---- 关系 ----
    cuisine: Mapped["Cuisine"] = relationship()
    geo_entity: Mapped["GeoEntity"] = relationship()

    # ---- 索引（GIN 索引 PostgreSQL 专用，SQLite 会忽略 postgresql_using）----
    __table_args__ = (
        Index("ix_dish_locality_score", "locality_score"),
        Index("ix_dish_admission", "admission_result"),
        Index("ix_dish_locality_level", "locality_level"),
        Index("ix_dish_geo_entity", "geo_entity_id"),
    )


# ============================================================================
# 商户（只读集成）
# ============================================================================


class Merchant(Base):
    __tablename__ = "merchant"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    geo_entity_id: Mapped[object] = mapped_column(ForeignKey("geo_entity.id"))
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    navigation_url: Mapped[Optional[str]] = mapped_column(String(500))
    source_name: Mapped[str] = mapped_column(String(100), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ============================================================================
# 用户画像（敏感数据）
# ============================================================================


class UserProfile(Base):
    __tablename__ = "user_profile"

    user_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    dietary_restrictions: Mapped[List[str]] = mapped_column(ListType(String), default=list)
    taste_preferences: Mapped[dict] = mapped_column(JSONDictType(), default=dict)
    family_profile_id: Mapped[Optional[object]] = mapped_column(ForeignKey("family_profile.id"))


class FamilyProfile(Base):
    __tablename__ = "family_profile"

    name: Mapped[str] = mapped_column(String(100))
    dietary_restrictions_merged: Mapped[List[str]] = mapped_column(ListType(String), default=list)
    taste_preferences_merged: Mapped[dict] = mapped_column(JSONDictType(), default=dict)


class FavoriteList(Base):
    __tablename__ = "favorite_list"

    user_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)


class FavoriteListItem(Base):
    __tablename__ = "favorite_list_item"

    list_id: Mapped[object] = mapped_column(ForeignKey("favorite_list.id"), nullable=False, index=True)
    dish_id: Mapped[object] = mapped_column(ForeignKey("dish.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ============================================================================
# 行为事件（埋点）
# ============================================================================


class BehaviorEvent(Base):
    __tablename__ = "behavior_event"

    user_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[object]] = mapped_column(UUID_Type())
    properties: Mapped[dict] = mapped_column(JSONDictType(), default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    __table_args__ = (
        Index("ix_behavior_user_time", "user_hash", "occurred_at"),
        Index("ix_behavior_event_time", "event_name", "occurred_at"),
    )
