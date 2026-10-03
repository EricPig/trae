"""推荐查询路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.engine.service import RecommendationEngine
from src.api.schemas import (
    DishCard,
    DishDetailRequest,
    DishDetailResponse,
    RecommendRequest,
    RecommendResponse,
    SearchRequest,
)

router = APIRouter(prefix="/api", tags=["recommend"])


def _to_card(r) -> DishCard:
    return DishCard(
        dish_id=r.dish_id,
        name=r.name,
        evidence_tag=r.evidence_tag,
        locality_score=r.locality_score,
        locality_level=r.locality_level,
        presentation=r.presentation.value if hasattr(r.presentation, "value") else r.presentation,
        source_name=r.source_name,
        verified_at=r.verified_at,
        cuisine_name=getattr(r, "cuisine_name", None),
        geo_name=getattr(r, "geo_name", None),
    )


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(req: RecommendRequest, session: AsyncSession = Depends(get_db_session)):
    """
    核心推荐接口。

    流程：
      1. DB 查询（筛选 admitted + 地理 + 菜系 + 过敏原排除）
      2. pipeline 纯函数（准入 + 安全 + 排序 + 展示）
      3. 诚实降级提示（数据源不足时）
    """
    engine = RecommendationEngine(session)
    results = await engine.recommend(
        city=req.city,
        cuisine=req.cuisine,
        dietary_restrictions=req.dietary_restrictions,
        exclude_chain=req.exclude_chain,
        max_items=req.max_items,
    )

    cards = [_to_card(r) for r in results]

    # 诚实降级提示
    notes: list[str] = []
    if not cards and req.city:
        notes.append(f"抱歉，在 {req.city} 我们暂时没有足够的数据源支撑推荐")
    elif any(r.presentation.value == "priority" for r in results):
        notes.append("部分条目资料有限，但为您保留了本地人推荐的好味道")

    return RecommendResponse(
        recommendations=cards,
        count=len(cards),
        notes=notes,
    )


@router.post("/search/discover", response_model=RecommendResponse)
async def discover(req: SearchRequest, session: AsyncSession = Depends(get_db_session)):
    """发现页：不设忌口的开放式推荐。"""
    engine = RecommendationEngine(session)
    results = await engine.search_discover(city=req.city, max_items=req.max_items)
    return RecommendResponse(
        recommendations=[_to_card(r) for r in results],
        count=len(results),
    )


@router.get("/dishes/{dish_id}", response_model=DishDetailResponse)
async def dish_detail(dish_id: str, session: AsyncSession = Depends(get_db_session)):
    """菜品详情页。"""
    engine = RecommendationEngine(session)
    dish = await engine.get_by_id(dish_id)
    if not dish:
        raise HTTPException(status_code=404, detail="未找到该菜品")

    # 用 pipeline 算它的展示层状态
    from src.engine.pipeline import resolve_presentation, adjudicate_admission
    admission = adjudicate_admission(dish.locality_level, dish.cuisine_evidence_level, dish.locality_score)
    presentation = resolve_presentation(admission, dish.cuisine_evidence_level, dish.locality_score)

    from src.config import EVIDENCE_MAPPING
    evidence_tag = EVIDENCE_MAPPING.get(dish.cuisine_evidence_level, "🟡")

    return DishDetailResponse(
        dish_id=str(dish.id),
        name=dish.name,
        description=dish.description,
        cuisine_name=dish.cuisine.name if dish.cuisine else None,
        geo_name=dish.geo_entity.name if dish.geo_entity else None,
        locality_level=dish.locality_level,
        cuisine_evidence_level=dish.cuisine_evidence_level,
        locality_score=dish.locality_score,
        admission_result=dish.admission_result,
        common_allergens=list(dish.common_allergens) if dish.common_allergens else [],
        allergen_info_complete=dish.allergen_info_complete,
        source_name=dish.source_name,
        source_version=dish.source_version,
        verified_at=dish.verified_at,
        data_conflict_note=dish.geo_conflict_note,
        presentation=presentation.value,
        evidence_tag=evidence_tag,
    )
