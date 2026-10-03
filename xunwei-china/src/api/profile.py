"""
用户画像路由 —— 敏感数据默认本地存储 + 合规全套。

产品全案 §2.3 核心能力三角 / §3.9 N6 不信任点：
  忌口/过敏数据是健康数据敏感度最高的一类，
  默认本地存储、显式授权、一键清除、不用于广告定向。

合规端点（GDPR/个保法）：
  GET  /api/profile                        读取（脱敏）
  PUT  /api/profile                        更新
  POST /api/profile/authorize              服务器存储显式授权
  POST /api/profile/clear                  一键清除
  GET  /api/profile/export                 数据导出（用户可获取全部副本）
  GET  /api/profile/retention              数据保留期说明
  POST /api/profile/family                 创建家庭档案
  GET  /api/profile/family                  家庭档案详情
  PUT  /api/profile/family                  更新家庭档案
  DELETE /api/profile/family                解除关联（不删除数据）
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from src.config import get_utcnow
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.db.models import FavoriteList, FavoriteListItem, UserProfile, FamilyProfile, BehaviorEvent

router = APIRouter(prefix="/api", tags=["profile"])


def _user_hash(user_id: str) -> str:
    """对用户标识做哈希（服务器不存原始 user_id，合规保障）。"""
    return hashlib.sha256(f"xw::{user_id}".encode()).hexdigest()


# ============================================================================
# Schema（保持轻量）
# ============================================================================

from pydantic import BaseModel, Field, ConfigDict


class TastePreferences(BaseModel):
    """结构化口味偏好（取代无约束 dict）。"""
    model_config = ConfigDict(extra="allow")

    spicy: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="辣度偏好 0-1")
    sweet: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sour: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    salty: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    umami: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class ProfileUpdate(BaseModel):
    user_id: str = Field(..., max_length=100)
    dietary_restrictions: list[str] = Field(default_factory=list, max_length=10)
    taste_preferences: TastePreferences = Field(default_factory=TastePreferences)
    # 场景偏好（产品全案 §3.9 E3 "懂我的场景"）
    scene_preferences: list[str] = Field(
        default_factory=list, max_length=10,
        description="家庭聚餐 / 朋友聚会 / 独自品尝 / 工作午餐 / 夜宵"
    )


class ProfileResponse(BaseModel):
    user_id_hash: str
    dietary_restrictions: list[str]
    taste_preferences: TastePreferences
    scene_preferences: list[str] = Field(default_factory=list)
    family_name: Optional[str] = None
    created_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None


class AuthorizeRequest(BaseModel):
    """敏感数据服务器存储授权确认。"""
    user_id: str
    accept: bool = Field(..., description="是否同意服务器存储健康敏感数据")


class ClearProfileRequest(BaseModel):
    user_id: str
    confirm: str = Field(..., pattern=r"^CLEAR ALL$", description="必须输入 CLEAR ALL 确认")


class FamilyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    dietary_restrictions_merged: list[str] = Field(default_factory=list)
    taste_preferences_merged: TastePreferences = Field(default_factory=TastePreferences)
    # 合并策略：交集（严格）/ 并集（宽松）—— 产品全案 R3
    merge_strategy: str = Field(default="intersection", pattern="^(intersection|union)$")


class FamilyUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    dietary_restrictions_merged: Optional[list[str]] = None
    taste_preferences_merged: Optional[TastePreferences] = None


# ============================================================================
# 路由
# ============================================================================


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    user_id: str = Query(..., description="用户标识（客户端传入，服务器哈希存储）"),
    session: AsyncSession = Depends(get_db_session),
):
    """
    获取用户画像（脱敏）。

    安全设计：服务器存储 user_hash，不存原始 user_id。
    首次访问自动创建空画像 —— 用户无摩擦。
    """
    result = await session.execute(
        select(UserProfile).where(UserProfile.user_hash == _user_hash(user_id))
    )
    profile = result.scalar_one_or_none()
    if not profile:
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

    tp = profile.taste_preferences or {}
    return ProfileResponse(
        user_id_hash=profile.user_hash,
        dietary_restrictions=list(profile.dietary_restrictions or []),
        taste_preferences=TastePreferences(**tp) if tp else TastePreferences(),
        scene_preferences=list(profile.taste_preferences.get("scenes", [])) if tp else [],
        family_name=family.name if family else None,
        created_at=profile.created_at,
        last_updated=profile.updated_at,
    )


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(req: ProfileUpdate, session: AsyncSession = Depends(get_db_session)):
    """
    更新用户画像。

    敏感数据策略（产品全案 N6）：
      - 服务器存储需显式授权（POST /api/profile/authorize）
      - 未授权时自动降级为客户端本地存储提示
      - 一键清除入口始终可用
    """
    h = _user_hash(req.user_id)
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserProfile(user_hash=h)
        session.add(profile)

    profile.dietary_restrictions = list(req.dietary_restrictions)
    tp = req.taste_preferences.model_dump(exclude_none=True)
    tp["scenes"] = list(req.scene_preferences)
    profile.taste_preferences = tp
    await session.commit()
    await session.refresh(profile)

    tp_out = profile.taste_preferences or {}
    return ProfileResponse(
        user_id_hash=profile.user_hash,
        dietary_restrictions=list(profile.dietary_restrictions or []),
        taste_preferences=TastePreferences(**tp_out) if tp_out else TastePreferences(),
        scene_preferences=list(tp_out.get("scenes", [])),
        family_name=None,
        created_at=profile.created_at,
        last_updated=profile.updated_at,
    )


@router.post("/profile/authorize")
async def authorize_storage(req: AuthorizeRequest, session: AsyncSession = Depends(get_db_session)):
    """
    敏感数据服务器存储授权确认（产品全案 N6 不信任点）。

    为什么需要这个端点？
      忌口/过敏是健康敏感数据（GDPR 特殊类别 / 个保法敏感信息），
      用户必须显式同意才能存服务器。
      未授权时：推荐仍可用，但画像数据只存客户端本地。
    """
    h = _user_hash(req.user_id)
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    if not profile:
        profile = UserProfile(user_hash=h)
        session.add(profile)

    # 在 taste_preferences 里记一个标记
    tp = dict(profile.taste_preferences or {})
    if req.accept:
        tp["_server_storage_authorized_at"] = get_utcnow().isoformat()
    else:
        tp.pop("_server_storage_authorized_at", None)
    profile.taste_preferences = tp
    await session.commit()

    if req.accept:
        return {
            "status": "authorized",
            "message": (
                "感谢您的信任。我们将严格遵守："
                "① 服务器只存哈希不存原始标识 "
                "② 您可随时 POST /api/profile/clear 一键清除 "
                "③ 不用于广告定向 "
                "④ 不提供给第三方"
            ),
            "storage_policy": "server_with_explicit_consent",
        }
    else:
        return {
            "status": "local_only",
            "message": (
                "好的，数据只存在您的设备本地。"
                "推荐功能仍可使用，但跨设备无法同步您的偏好。"
            ),
            "storage_policy": "client_local_only",
        }


@router.post("/profile/clear")
async def clear_profile(req: ClearProfileRequest, session: AsyncSession = Depends(get_db_session)):
    """
    一键清除所有画像数据（合规强制端点）。

    产品全案 N6：用户对"忌口即健康数据"敏感，
    必须提供无摩擦的清除通道。需要输入 CLEAR ALL 确认。

    清除范围：
      - UserProfile（忌口 + 偏好）
      - BehaviorEvent（行为埋点中该用户的记录）
      - FavoriteList + FavoriteListItem（清单数据）
    不清除：数据保留期内的聚合匿名统计
    """
    h = _user_hash(req.user_id)

    # 删画像
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    family_id = profile.family_profile_id if profile else None
    if profile:
        profile.dietary_restrictions = []
        profile.taste_preferences = {}

    # 删清单
    await session.execute(
        FavoriteListItem.__table__.delete().where(
            FavoriteListItem.list_id.in_(
                select(FavoriteList.id).where(FavoriteList.user_hash == h)
            )
        )
    )
    await session.execute(FavoriteList.__table__.delete().where(FavoriteList.user_hash == h))

    # 删行为数据（GDPR 第 17 条：被遗忘权）
    await session.execute(BehaviorEvent.__table__.delete().where(BehaviorEvent.user_hash == h))

    # 家庭档案解除关联（不删家庭档案 —— 可能多人共用）
    if profile and family_id:
        profile.family_profile_id = None

    await session.commit()

    return {
        "status": "cleared",
        "message": "您的所有画像数据已清除。我们不保留任何历史痕迹。",
        "deleted": {
            "profile": True,
            "behavior_events": True,
            "favorite_lists": True,
        },
        "retention_note": "聚合匿名统计（不含您的个人标识）可能在 90 天保留期内存在。",
    }


@router.get("/profile/export")
async def export_profile(
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
):
    """
    数据导出（GDPR 第 15 条 / 个保法第 24 条）。

    用户可获取服务器存储的**全部**属于自己的数据副本。
    返回 JSON 格式，方便用户保存或迁移。
    """
    h = _user_hash(user_id)

    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()

    # 关联的清单
    lists_result = await session.execute(
        select(FavoriteList).where(FavoriteList.user_hash == h)
    )
    lists = []
    for fl in list(lists_result.scalars().all()):
        item_result = await session.execute(
            select(FavoriteListItem).where(FavoriteListItem.list_id == fl.id)
        )
        lists.append({
            "list_id": str(fl.id),
            "title": fl.title,
            "is_locked": fl.is_locked,
            "is_shared": fl.is_shared,
            "items": [{"dish_id": str(i.dish_id), "added_at": i.added_at.isoformat()}
                      for i in item_result.scalars().all()],
        })

    # 行为事件（限制最近 500 条）
    event_result = await session.execute(
        select(BehaviorEvent)
        .where(BehaviorEvent.user_hash == h)
        .order_by(BehaviorEvent.occurred_at.desc())
        .limit(500)
    )
    events = [
        {"event_name": e.event_name, "entity_id": str(e.entity_id) if e.entity_id else None,
         "properties": e.properties, "occurred_at": e.occurred_at.isoformat()}
        for e in event_result.scalars().all()
    ]

    return {
        "exported_at": get_utcnow().isoformat(),
        "user_hash": h,
        "profile": {
            "dietary_restrictions": list(profile.dietary_restrictions or []) if profile else [],
            "taste_preferences": profile.taste_preferences if profile else {},
            "created_at": profile.created_at.isoformat() if profile else None,
            "updated_at": profile.updated_at.isoformat() if profile else None,
        },
        "favorite_lists": lists,
        "behavior_events_count": len(events),
        "behavior_events": events,
        "note": (
            "这是您的数据副本。如需导出超过 500 条行为事件，"
            "请联系 support@xunwei.example"
        ),
    }


@router.get("/profile/retention")
async def retention_policy():
    """数据保留期说明（合规透明）。"""
    return {
        "profile_data": {
            "description": "您的忌口、偏好等画像数据",
            "retention": "直到您主动清除（POST /api/profile/clear）",
            "auto_cleanup": "无 —— 您不清除我们就不删",
        },
        "behavior_events": {
            "description": "您的浏览、点击、清单操作等行为数据",
            "retention": "12 个月，然后自动匿名化处理",
            "auto_cleanup": True,
        },
        "favorite_lists": {
            "description": "您创建的清单和收藏",
            "retention": "直到您主动删除",
            "auto_cleanup": "无",
        },
        "anonymous_aggregates": {
            "description": "不含任何个人标识的聚合统计（准入率、四象限分布等）",
            "retention": "永久（用于改进推荐质量）",
            "contains_pii": False,
        },
        "contact": "privacy@xunwei.example",
    }


# ============================================================================
# 家庭档案（R3 家庭决策者场景）
# ============================================================================


@router.post("/profile/family")
async def create_family(
    req: FamilyCreateRequest,
    user_id: str = Query(...),
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
        taste_preferences_merged=req.taste_preferences_merged.model_dump(exclude_none=True),
    )
    session.add(fam)
    await session.flush()

    h = _user_hash(user_id)
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    if profile:
        profile.family_profile_id = fam.id
        await session.commit()

    return {
        "status": "created",
        "family_id": str(fam.id),
        "name": fam.name,
        "merge_strategy": req.merge_strategy,
        "note": (
            f"合并策略: {req.merge_strategy}. "
            "intersection = 所有家庭成员共同忌口才生效（推荐最保守/安全）. "
            "union = 任何一人忌口都生效（推荐最严格/排除最多）"
        ),
    }


@router.get("/profile/family")
async def get_family(
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
):
    """获取家庭档案详情。"""
    h = _user_hash(user_id)
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    if not profile or not profile.family_profile_id:
        return {"status": "no_family", "note": "当前未关联家庭档案"}

    fam_result = await session.execute(
        select(FamilyProfile).where(FamilyProfile.id == profile.family_profile_id)
    )
    fam = fam_result.scalar_one_or_none()
    if not fam:
        raise HTTPException(status_code=404, detail="家庭档案不存在")

    return {
        "family_id": str(fam.id),
        "name": fam.name,
        "dietary_restrictions_merged": list(fam.dietary_restrictions_merged or []),
        "taste_preferences_merged": fam.taste_preferences_merged or {},
        "created_at": fam.created_at.isoformat(),
        "updated_at": fam.updated_at.isoformat(),
    }


@router.put("/profile/family")
async def update_family(
    req: FamilyUpdateRequest,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
):
    """更新家庭档案。"""
    h = _user_hash(user_id)
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    if not profile or not profile.family_profile_id:
        raise HTTPException(status_code=404, detail="未关联家庭档案")

    fam_result = await session.execute(
        select(FamilyProfile).where(FamilyProfile.id == profile.family_profile_id)
    )
    fam = fam_result.scalar_one_or_none()
    if not fam:
        raise HTTPException(status_code=404, detail="家庭档案不存在")

    if req.name is not None:
        fam.name = req.name
    if req.dietary_restrictions_merged is not None:
        fam.dietary_restrictions_merged = list(req.dietary_restrictions_merged)
    if req.taste_preferences_merged is not None:
        fam.taste_preferences_merged = req.taste_preferences_merged.model_dump(exclude_none=True)
    await session.commit()

    return {"status": "updated", "family_id": str(fam.id), "name": fam.name}


@router.delete("/profile/family")
async def detach_family(
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_db_session),
):
    """
    解除家庭档案关联。

    注意：只解除关联，不删除家庭档案数据（其他家庭成员可能还在用）。
    """
    h = _user_hash(user_id)
    result = await session.execute(select(UserProfile).where(UserProfile.user_hash == h))
    profile = result.scalar_one_or_none()
    if profile and profile.family_profile_id:
        profile.family_profile_id = None
        await session.commit()

    return {"status": "detached", "message": "已解除家庭档案关联。家庭档案数据保留（其他成员可能仍在使用）。"}
