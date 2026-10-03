"""行为埋点 SDK（前端 + 后端）。

架构职责：
  - 前端埋点：收集用户行为事件，异步上报
  - 后端接收：/api/event 端点，fire-and-forget 到消息队列
  - 指标计算：WDCU + 辅助指标

事件模型：
  dish_detail_view   — 详情页深度消费（≥60s + 滚动锚点）
  menu_add           — 加入清单
  fav_add            — 加入收藏
  nav_redirect       — 导航跳转
  chat_decide        — AI 对话 "就它了"
  list_lock          — 清单锁定（WDCU 主指标）
  list_share         — 清单分享（WDCU 主指标）
  post_visit_feedback — 消费后反馈（WDCU 主指标）

设计原则：
  - 不阻塞主请求
  - 幂等（同一事件不重复写入）
  - 数据最小化（不采集敏感信息）
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from src.config import get_utcnow
from typing import Optional

# WDCU 的有效决策事件名（产品全案 §2.4）
WDCU_DECISION_EVENTS = frozenset({
    "dish_detail_view",
    "menu_add",
    "fav_add",
    "nav_redirect",
    "chat_decide",
    "list_lock",
    "list_share",
    "post_visit_feedback",
})


@dataclass
class BehaviorEventPayload:
    """行为事件（前端 → 后端）。"""

    user_hash: str  # 用户标识（哈希后），不存原始 user_id
    event_name: str
    entity_id: Optional[str] = None
    properties: dict = field(default_factory=dict)
    occurred_at: Optional[datetime] = None

    def to_db_row(self) -> dict:
        return {
            "user_hash": self.user_hash,
            "event_name": self.event_name,
            "entity_id": self.entity_id,
            "properties": self.properties,
            "occurred_at": self.occurred_at or get_utcnow(),
        }

    @property
    def is_wdcu_decision(self) -> bool:
        return self.event_name in WDCU_DECISION_EVENTS


# ============================================================================
# 前端 SDK（Python 模拟版，实际应是 JS SDK）
# ============================================================================


class FrontendTracker:
    """前端埋点 SDK（骨架）。"""

    def __init__(self, endpoint: str, user_id: str | None = None) -> None:
        self.endpoint = endpoint
        self._user_hash: str | None = None
        if user_id:
            self.set_user(user_id)

    def set_user(self, user_id: str) -> None:
        """设置用户标识（哈希后存储，不存原始 ID）。"""
        self._user_hash = hashlib.sha256(f"xw::{user_id}".encode()).hexdigest()

    async def track(self, event_name: str, entity_id: str | None = None, properties: dict | None = None) -> None:
        """
        上报事件（fire-and-forget）。

        实际实现：
          JS SDK 用 navigator.sendBeacon 或 fetch(keepalive:true)
          后端接收后写入 Redis Stream / Kafka
        """
        if not self._user_hash:
            return  # 未登录用户不采集

        payload = BehaviorEventPayload(
            user_hash=self._user_hash,
            event_name=event_name,
            entity_id=entity_id,
            properties=properties or {},
        )
        # 实际发送实现...
        _ = payload  # 占位


# ============================================================================
# WDCU 计算
# ============================================================================


def compute_wdcu(events: list[dict], week_start: datetime) -> dict:
    """
    计算 WDCU（Weekly Decision-Completed Users）。

    定义（产品全案 §2.4）：
      自然周内，至少完成 1 次有效决策的去重用户数

    有效决策事件：8 类（见 WDCU_DECISION_EVENTS）
    """
    decision_users: set[str] = set()
    event_counts: dict[str, int] = {}

    for ev in events:
        name = ev.get("event_name", "")
        if name in WDCU_DECISION_EVENTS:
            decision_users.add(ev.get("user_hash", ""))
            event_counts[name] = event_counts.get(name, 0) + 1

    return {
        "week_start": week_start.date().isoformat(),
        "wdcu": len(decision_users),
        "decision_events_by_type": event_counts,
    }
