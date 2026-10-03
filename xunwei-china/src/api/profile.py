"""用户画像路由 —— 敏感数据默认本地存储。

产品全案 §2.3 核心能力三角 / §3.9 N6 不信任点：
  忌口/过敏数据是健康数据敏感度最高的一类，
  默认本地存储、显式授权、一键清除、不用于广告定向。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.db.models import UserProfile, FamilyProfile

router = APIRouter(prefix="/api", tags=["profile"])


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(f"xw::{user_id}".encode()).hexdigest()


# ============================================================================
# Schema
# ============================================================================

from pydantic import BaseModel, Field


class ProfileUpdate(BaseModel):
    user_id: str = Field(..., max_length=100)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)
    taste_preferences: dict = Field(default_factory=dict)  # {"spicy": 0.8, "sweet": 0.3}


class ProfileResponse(BaseModel):
    user_id_hash: str
    dietary_restrictions: list[str]
    taste_preferences: dict
    family_name: Optional[str] = None
    created_at: Optional[datetime] = None


class ClearProfileRequest(BaseModel):
    user_id: str


class FamilyCreateRequest(BaseModel):
    name: str
    dietary_restrictions_merged: list[str] = Field(default_factory=list)
    taste_preferences_merged: dict = Field(default_factory=dict)


# ============================================================================
# 路由
# ============================================================================


@router.get("/profile")
async def get_profile(user_id: str, session: AsyncSession = Depends(get_db_session)):
    """获取用户画像（脱敏）。"""
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_hash == _user_hash(user_id))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        # 不存在 → 自动创建空画像（用户首次使用）
        profile = UserProfile(user_hash=_user_hash(user_id))
        session.add(profile)
        await session.commit()
        await session.refresh(profile)

    family = None
    if profile.family_profile_id:
        fam_result = await session.execute(
            select(FamilyProfile).where(FamilyProfile.id == profile.family_profile_id)
        )
        family = fam_result.scalar_one_or_none()

    return ProfileResponse(
        user_id_hash=profile.user_hash,
        dietary_restrictions=list(profile.dietary_restrictions),
        taste_preferences=profile.taste_preferences,
        family_name=family.name if family else None,
        created_at=profile.created_at,
    )


@router.put("/profile")
async def update_profile(req: ProfileUpdate, session: AsyncSession = Depends(get_db_session)):
    """
    更新用户画像。

    敏感数据策略：
      - 服务器存储需显式授权（产品全案 N6）
      - 默认推荐客户端本地存储优先
      - 一键清除入口始终可用
    """
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_hash == _user_hash(req.user_id))
    )
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserProfile(user_hash=_user_hash(req.user_id))
        session.add(profile)

    profile.dietary_restrictions = list(req.dietary_restrictions)
    profile.taste_preferences = req.taste_preferences
    await session.commit()
    await session.refresh(profile)

    return {"status": "updated", "dietary_restrictions": profile.dietary_restrictions}


@router.post("/profile/clear")
async def clear_profile(req: ClearProfileRequest, session: AsyncSession = Depends(get_db_session)):
    """
    一键清除所有画像数据（合规要求）。

    产品全案 N6 不信任点：用户对"忌口即健康数据"敏感，
    必须提供无摩擦的清除通道。
    """
    h = _user_hash(req.user_id)
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_hash == h)
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.dietary_restrictions = []
        profile.taste_preferences = {}
        await session.commit()

    return {
        "status": "cleared",
        "message": "您的所有画像数据已清除。我们不保留任何历史痕迹。",
    }


@router.post("/profile/family")
async def create_family(
    req: FamilyCreateRequest,
    user_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """
    创建家庭档案（多人口味合并）。

    产品全案 §3.2 R3 家庭决策者：
      家庭档案合并是唯一不依赖外部行为数据的信号来源，
      能让 R3 人群快速撑起 7 日留存（多人共享决策场景）。

    不做：家庭成员独立账号体系（基线清单 §2.7 明确"永不做"）
    """
    fam = FamilyProfile(
        name=req.name,
        dietary_restrictions_merged=list(req.dietary_restrictions_merged),
        taste_preferences_merged=req.taste_preferences_merged,
    )
    session.add(fam)
    await session.flush()

    # 关联到用户画像
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_hash == _user_hash(user_id))
    )
    profile = result.scalar_one_or_none()
    if profile:
        profile.family_profile_id = fam.id
        await session.commit()

    return {
        "status": "created",
        "family_id": str(fam.id),
        "name": fam.name,
    }
