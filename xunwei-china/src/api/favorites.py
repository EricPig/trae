"""清单/收藏路由 —— WDCU 主指标入口。

WDCU 有效决策事件：
  list_lock / list_share    ← 本模块核心
  menu_add / fav_add        ← 收藏功能
  post_visit_feedback       ← 消费后反馈（闭环）
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.db.models import FavoriteList, FavoriteListItem

router = APIRouter(prefix="/api", tags=["favorites"])


def _user_hash(user_id: str) -> str:
    """对用户标识做哈希（安全：服务器不存原始 user_id）。"""
    return hashlib.sha256(f"xw::{user_id}".encode()).hexdigest()


# ============================================================================
# Schema（保持轻量，避免污染 src/api/schemas.py 的 API 主契约）
# ============================================================================

from pydantic import BaseModel, Field


class CreateListRequest(BaseModel):
    user_id: str = Field(..., max_length=100)
    title: str = Field(..., min_length=1, max_length=200)


class AddItemRequest(BaseModel):
    user_id: str = Field(..., max_length=100)
    list_id: str
    dish_id: str


class LockListRequest(BaseModel):
    user_id: str = Field(..., max_length=100)
    list_id: str


class ShareListRequest(BaseModel):
    user_id: str = Field(..., max_length=100)
    list_id: str


class ListResponse(BaseModel):
    list_id: str
    title: str
    item_count: int
    is_locked: bool
    is_shared: bool


# ============================================================================
# 路由
# ============================================================================


@router.post("/lists", response_model=ListResponse)
async def create_list(req: CreateListRequest, session: AsyncSession = Depends(get_db_session)):
    """创建清单。"""
    fl = FavoriteList(
        user_hash=_user_hash(req.user_id),
        title=req.title,
    )
    session.add(fl)
    await session.commit()
    await session.refresh(fl)
    return ListResponse(
        list_id=str(fl.id),
        title=fl.title,
        item_count=0,
        is_locked=fl.is_locked,
        is_shared=fl.is_shared,
    )


@router.post("/lists/items")
async def add_item(req: AddItemRequest, session: AsyncSession = Depends(get_db_session)):
    """
    添加菜品到清单。

    这是 WDCU 的 menu_add / fav_add 事件（产品全案 §2.4）。
    实现层：写入 DB + 触发埋点（analytics 模块处理）。
    """
    # 验证清单归属
    result = await session.execute(
        select(FavoriteList).where(
            FavoriteList.id == UUID(req.list_id),
            FavoriteList.user_hash == _user_hash(req.user_id),
        )
    )
    fl = result.scalar_one_or_none()
    if not fl:
        raise HTTPException(status_code=404, detail="清单不存在或无权限")

    item = FavoriteListItem(list_id=fl.id, dish_id=UUID(req.dish_id))
    session.add(item)
    await session.commit()

    return {"status": "ok", "list_id": req.list_id, "dish_id": req.dish_id}


@router.get("/lists")
async def list_lists(user_id: str, session: AsyncSession = Depends(get_db_session)):
    """获取用户的所有清单。"""
    result = await session.execute(
        select(FavoriteList).where(FavoriteList.user_hash == _user_hash(user_id))
    )
    lists = list(result.scalars().all())

    # 计数（简化版，T1 后可加聚合查询）
    resp = []
    for fl in lists:
        count_result = await session.execute(
            select(FavoriteListItem).where(FavoriteListItem.list_id == fl.id)
        )
        resp.append(
            ListResponse(
                list_id=str(fl.id),
                title=fl.title,
                item_count=len(count_result.scalars().all()),
                is_locked=fl.is_locked,
                is_shared=fl.is_shared,
            )
        )
    return resp


@router.post("/lists/lock")
async def lock_list(req: LockListRequest, session: AsyncSession = Depends(get_db_session)):
    """
    锁定清单 —— WDCU 核心事件。

    产品全案 §2.4：list_lock 是 8 类有效决策事件之一。
    用户锁定清单 = "这个行程我确定了" = 完成有效决策。
    """
    result = await session.execute(
        select(FavoriteList).where(
            FavoriteList.id == UUID(req.list_id),
            FavoriteList.user_hash == _user_hash(req.user_id),
        )
    )
    fl = result.scalar_one_or_none()
    if not fl:
        raise HTTPException(status_code=404, detail="清单不存在或无权限")

    fl.is_locked = True
    await session.commit()

    return {
        "status": "locked",
        "list_id": req.list_id,
        "note": "✅ 清单锁定 —— 这是您的决策，不会被优化或改变",
    }


@router.post("/lists/share")
async def share_list(req: ShareListRequest, session: AsyncSession = Depends(get_db_session)):
    """
    分享清单 —— WDCU 核心事件。

    list_share 也是 8 类有效决策事件之一（与 list_lock 并列）。
    """
    result = await session.execute(
        select(FavoriteList).where(
            FavoriteList.id == UUID(req.list_id),
            FavoriteList.user_hash == _user_hash(req.user_id),
        )
    )
    fl = result.scalar_one_or_none()
    if not fl:
        raise HTTPException(status_code=404, detail="清单不存在或无权限")

    fl.is_shared = True
    await session.commit()

    return {
        "status": "shared",
        "list_id": req.list_id,
        "share_url": f"/share/{req.list_id}",
    }


@router.delete("/lists/{list_id}")
async def delete_list(list_id: str, user_id: str, session: AsyncSession = Depends(get_db_session)):
    """删除清单。"""
    await session.execute(
        delete(FavoriteListItem).where(FavoriteListItem.list_id == UUID(list_id))
    )
    await session.execute(
        delete(FavoriteList).where(
            FavoriteList.id == UUID(list_id),
            FavoriteList.user_hash == _user_hash(user_id),
        )
    )
    await session.commit()
    return {"status": "ok", "message": "清单已删除"}
