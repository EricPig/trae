"""
推荐引擎服务层（Engine API）。

职责：
  - 从数据库拉取候选（src/db/queries.py）
  - 转换为 pipeline.pipeline() 需要的 dict 格式
  - 调用纯函数 pipeline 做准入 → 安全 → 排序 → 展示
  - 返回 Recommendation 对象列表

不做：
  - 直接写 SQL（委托给 queries.py）
  - 数据库连接管理（委托给 db/connection.py）
  - AI 对话（委托给 ai/pipeline.py）

ACL 物理隔离（FF-ARCH-03/04）：
  - 只有 recommend / search_discover / get_evidence_batch 三个方法对 AI 层开放
  - get_by_id 是 API 层详情页专用，AI 层禁止调用
  - 内部辅助方法（_dish_to_dict）不对外暴露
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.acl import acl_guard  # B2 ACL runtime guard
from src.db.models import Dish
from src.db.queries import build_recommendation_query
from src.engine.pipeline import (
    PresentationTier,
    Recommendation,
    pipeline as run_pipeline,
)


class RecommendationEngine:
    """推荐引擎服务（单体优先，模块边界清晰）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ============================================================================
    # 公开 API（ACL 白名单方法）
    # ============================================================================

    @acl_guard
    async def recommend(
        self,
        city: Optional[str] = None,
        cuisine: Optional[str] = None,
        dietary_restrictions: Optional[list[str]] = None,
        exclude_chain: bool = True,
        max_items: int = 10,
    ) -> list[Recommendation]:
        """
        核心推荐方法（ACL 白名单：AI 层唯一数据通道）。

        流程：
          1. DB 查询（筛选 admitted + 地理 + 菜系 + 过敏原排除）
          2. ORM → dict 转换
          3. 纯函数 pipeline（准入 + 安全 + 排序 + 展示）
          4. 返回排序后的 Recommendation 列表
        """
        # 1. DB 查询
        dishes = await build_recommendation_query(
            session=self.session,
            city_name=city,
            cuisine_name=cuisine,
            user_restrictions=dietary_restrictions,
            max_items=max_items,
        )

        # 2. ORM → dict（pipeline 纯函数需要 dict 输入）
        candidates = [self._dish_to_dict(d) for d in dishes]

        # 3. 纯函数 pipeline（埋点：准入/安全/分数分布）
        results = run_pipeline(candidates, user_restrictions=dietary_restrictions)

        # B4 Prometheus 业务层埋点（不影响 pipeline 纯函数特性）
        try:
            from src.analytics.metrics import (
                xw_pipeline_admission, xw_pipeline_safety_filter,
                xw_pipeline_locality_score, xw_pipeline_duration,
            )
            from src.engine.pipeline import AdmissionDecision, SafetyStatus

            # locality_score 分布
            for r in results:
                xw_pipeline_locality_score.observe(r.locality_score)

            # 准入判定（只统计 candidates 里发生了什么，不只是最终 admitted）
            for c in candidates:
                adm = c.get("admission_result", "admitted")
                xw_pipeline_admission.labels(decision=adm).inc()

            # 安全层排除
            for c in candidates:
                completeness = c.get("allergen_info_complete", False)
                if dietary_restrictions and c.get("common_allergens"):
                    hits = set(c["common_allergens"]) & set(dietary_restrictions)
                    if hits:
                        xw_pipeline_safety_filter.labels(reason="allergen_miss").inc()
                if not completeness:
                    xw_pipeline_safety_filter.labels(reason="unknown_completeness").inc()

            xw_pipeline_duration.labels(city=city or "unknown").observe(
                0.0  # 耗时在 HTTP middleware 层统计，这里只打业务语义
            )
        except ImportError:
            pass  # 无 prometheus_client 时跳过（不影响功能）

        # 4. 截断
        return results[:max_items]

    @acl_guard
    async def search_discover(
        self,
        city: Optional[str] = None,
        max_items: int = 20,
    ) -> list[Recommendation]:
        """
        发现页：不设忌口，只按展示层最佳候选排序。
        ACL 白名单方法（AI 层可调用）。
        """
        return await self.recommend(
            city=city,
            dietary_restrictions=[],
            max_items=max_items,
        )

    async def get_by_id(self, dish_id: str) -> Optional[Dish]:
        """
        按 ID 获取单个 Dish（**API 层详情页专用，ACL 非白名单**）。

        AI 层调用此方法会触发 ACLViolation（因为这会绕过 pipeline 直接返回 ORM 对象，
        可能泄漏数据库结构或未经过 pipeline 过滤的原始数据）。

        如果 AI 层需要单条菜品证据 → 用 get_evidence_batch。
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from uuid import UUID

        # ACL runtime guard：检查调用栈是否有 src.ai.* 模块
        from src.ai.acl import _acl_runtime_guard
        _acl_runtime_guard("get_by_id")

        # eager load 关联对象 —— async session 禁止懒加载
        result = await self.session.execute(
            select(Dish)
            .where(Dish.id == UUID(dish_id))
            .options(
                selectinload(Dish.cuisine),
                selectinload(Dish.geo_entity),
            )
        )
        return result.scalar_one_or_none()

    @acl_guard
    async def get_evidence_batch(self, dish_ids: list[str]) -> dict[str, Any]:
        """
        获取菜品证据链（ACL 白名单：AI RAG 唯一证据通道）。

        返回 EvidenceChain 对象（不是原始 Dish ORM），
        防止 AI 层拿到数据库结构或绕过 pipeline 安全过滤。
        """
        from sqlalchemy import select
        from uuid import UUID
        from src.ai.pipeline import EvidenceChain

        if not dish_ids:
            return {}

        uuids = [UUID(did) for did in dish_ids]
        result = await self.session.execute(
            select(Dish).where(Dish.id.in_(uuids))
        )
        dishes = list(result.scalars().all())

        evidence_map: dict[str, EvidenceChain] = {}
        for d in dishes:
            completeness = "complete" if d.verified_at else "missing"
            evidence_map[str(d.id)] = EvidenceChain(
                dish_id=str(d.id),
                source_name=d.source_name or "",
                verified_at=d.verified_at,
                completeness=completeness,
                notes=d.geo_conflict_note if d.geo_conflict else None,
                has_allergy_data=d.allergen_info_complete,
                geo_conflict=d.geo_conflict,
            )

        return evidence_map

    # ============================================================================
    # 内部辅助
    # ============================================================================

    @staticmethod
    def _dish_to_dict(d: Dish) -> dict:
        """
        ORM → pipeline 输入格式（内部静态方法，ACL 不关心）。

        pipeline 是纯函数，只接受 dict 输入（不依赖 SQLAlchemy）。
        这里做显式转换，避免在 pipeline 里出现 ORM 属性访问。
        """
        return {
            "id": str(d.id),
            "name": d.name,
            "locality_level": d.locality_level,
            "evidence_level": d.cuisine_evidence_level,
            "locality_score": d.locality_score,
            "establishment_year": d.establishment_year,
            "common_allergens": list(d.common_allergens) if d.common_allergens else [],
            "allergen_info_complete": d.allergen_info_complete,
            "source_name": d.source_name,
            "verified_at": d.verified_at,
            "native_score": d.native_score,
            "years_factor": d.years_factor,
            "cuisine_factor": d.cuisine_factor,
            # 可选关联
            "cuisine_name": d.cuisine.name if d.cuisine else None,
            "geo_name": d.geo_entity.name if d.geo_entity else None,
        }
