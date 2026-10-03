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

设计原则：
  - 服务层是 IO 边界，pipeline 是纯函数（可独立测试）
  - 每一层的职责单一，便于替换和降级
  - 推荐逻辑的正确性由 pipeline 守护（R1-R5 断言）
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

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
    # 公开 API
    # ============================================================================

    async def recommend(
        self,
        city: Optional[str] = None,
        cuisine: Optional[str] = None,
        dietary_restrictions: Optional[list[str]] = None,
        exclude_chain: bool = True,
        max_items: int = 10,
    ) -> list[Recommendation]:
        """
        核心推荐方法。

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

        # 3. 纯函数 pipeline
        results = run_pipeline(candidates, user_restrictions=dietary_restrictions)

        # 4. 截断
        return results[:max_items]

    async def search_discover(
        self,
        city: Optional[str] = None,
        max_items: int = 20,
    ) -> list[Recommendation]:
        """
        发现页：不设忌口，只按展示层最佳候选排序。

        用于"成都有什么好吃的"这类开放式搜索。
        """
        return await self.recommend(
            city=city,
            dietary_restrictions=[],
            max_items=max_items,
        )

    async def get_by_id(self, dish_id: str) -> Optional[Dish]:
        """按 ID 获取单个 Dish（详情页用）。"""
        from sqlalchemy import select
        from uuid import UUID

        result = await self.session.execute(
            select(Dish).where(Dish.id == UUID(dish_id))
        )
        return result.scalar_one_or_none()

    async def get_evidence_batch(self, dish_ids: list[str]) -> dict[str, Any]:
        """
        获取菜品证据链（AI RAG 用）。

        注意：这是 ACL 的唯一数据通道（供 AI 子系统调用），
        返回 EvidenceChain 对象（不是原始 Dish ORM）。
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
        ORM → pipeline 输入格式。

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
