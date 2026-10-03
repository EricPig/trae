"""元数据路由 —— 地理发现 / 菜系列表 / 能力档位声明。

产品全案 §3.9 E2–E5 期待：
  帮我做决定（Top3 收敛）· 说出依据（五要素）· 记住我是谁（画像）·
  懂我的场景（结构化输入）· 敢承认不知道（诚实拒答 + 能力档位）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.db.models import Cuisine, Dish, GeoEntity
from src.config import (
    SAFETY_VIOLATION_TARGET,
    HALLUCINATION_TARGET,
    SOURCE_ANNOTATION_TARGET,
)

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/meta/capability")
async def capability_statement():
    """
    诚实能力档位声明（产品全案 §3.9 E5）。

    任何时候用户想知道"这个 AI 能做什么、不能做什么"，
    都应该能找到这个端点。固定模板，不编造。
    """
    return {
        "name": "寻味中国 AI",
        "statement": (
            "我是「寻味中国」的推荐助手。我能帮你在指定城市"
            "按你的口味、忌口、场景条件筛选本地美食推荐。"
            "所有推荐都带来源和核验时间。"
            "但我不知道的地方就说不知道，"
            "不编造，不瞎推荐。"
        ),
        "can_do": [
            "在一个城市内，根据你的条件（忌口、菜系、预算）筛选本地美食",
            "对每条推荐给出依据（技法、食材来源、历史背景、适合场景）",
            "记住你的忌口和偏好（可选）",
            "告诉你每条推荐的信息来源和核验时间",
        ],
        "cannot_do": [
            "我不保证门店当前营业状态",
            "我不提供实时价格",
            "我不替代专业的饮食医疗建议",
            "我不做商户评分排名",
        ],
        "red_lines": {
            "allergen_violation_target_pct": SAFETY_VIOLATION_TARGET,
            "hallucination_target_pct": HALLUCINATION_TARGET,
            "source_annotation_target_pct": SOURCE_ANNOTATION_TARGET,
            "note": "这些是架构级常量，运行时由 FF-SAFE-01/02 和 FF-DATA-01 守护",
        },
        "commercial_disclosure": (
            "我们的推荐结果可能包含平台导流链接，点击外部地图"
            "可能产生佣金。推荐层与导流层物理隔离，导流信号不影响推荐排序。"
        ),
        "version": "0.1.0",
    }


@router.get("/meta/cities")
async def list_cities(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
):
    """已覆盖的城市列表 + 菜品数统计。"""
    from sqlalchemy import func, select as sa_select

    # 先找到有菜品的 geo_entity_id
    dish_subquery = (
        sa_select(Dish.geo_entity_id, func.count(Dish.id).label("dish_count"))
        .where(Dish.admission_result == "admitted")
        .group_by(Dish.geo_entity_id)
        .subquery()
    )

    result = await session.execute(
        sa_select(GeoEntity.name, GeoEntity.level, dish_subquery.c.dish_count)
        .join(dish_subquery, GeoEntity.id == dish_subquery.c.geo_entity_id)
        .order_by(dish_subquery.c.dish_count.desc())
        .limit(limit)
    )
    rows = result.all()

    return {
        "cities": [
            {"name": r[0], "level": r[1], "dish_count": r[2]} for r in rows
        ],
        "total": len(rows),
    }


@router.get("/meta/cuisines")
async def list_cuisines(
    session: AsyncSession = Depends(get_db_session),
):
    """菜系列表（含子菜系层级）。"""
    result = await session.execute(
        select(Cuisine).order_by(Cuisine.name)
    )
    cuisines = list(result.scalars().all())
    return {
        "cuisines": [
            {"name": c.name, "parent": c.parent_id} for c in cuisines
        ],
        "total": len(cuisines),
    }


@router.get("/meta/allergen-types")
async def list_allergen_types():
    """常见过敏原类型（供 UI 多选）。T0 阶段静态列表。"""
    common = [
        {"name": "花生", "allergen_type": "花生", "severity": "high"},
        {"name": "牛奶", "allergen_type": "乳制品", "severity": "high"},
        {"name": "鸡蛋", "allergen_type": "蛋类", "severity": "high"},
        {"name": "虾/海鲜", "allergen_type": "海鲜", "severity": "high"},
        {"name": "大豆", "allergen_type": "大豆", "severity": "medium"},
        {"name": "小麦/麸质", "allergen_type": "麸质", "severity": "medium"},
        {"name": "坚果", "allergen_type": "坚果", "severity": "high"},
        {"name": "辣椒", "allergen_type": "辛辣", "severity": "medium", "note": "通常非过敏，仅对消化道敏感者有影响"},
    ]
    return {
        "common": common,
        "note": "T0 阶段常见过敏原列表，完整数据在 Ingredient 表",
    }


@router.get("/meta/version")
async def version():
    """版本信息 + 架构不变量状态。"""
    from scripts.verify_s0_weights import run_assertions

    assertions = run_assertions()
    return {
        "version": "0.1.0",
        "phase": "T0 立项验证",
        "architecture_assertions": {
            a.name: "passed" if a.passed else "FAILED"
            for a in assertions
        },
        "all_assertions_pass": all(a.passed for a in assertions),
        "docs": "/architecture/",
    }
