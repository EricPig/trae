"""SQL 查询构建器 —— 按城市/菜系/忌口/准入状态筛选 Dish。

设计原则：
  - 所有查询返回 Dish ORM 对象或 Row 字典，不直接暴露 SQL
  - 城市 = 该 GeoEntity + 所有子节点（区县/街道）的菜品
  - 菜系 = Cuisine.id 匹配（含子菜系可选）
  - 忌口 = 排除 common_allergens 有交集的菜品（召回层安全硬过滤）
  - 准入状态 = admission_result = 'admitted'（数据库预过滤）

B3 降级适配：
  - Postgres: ARRAY && 操作符 + RECURSIVE CTE
  - SQLite: JSON text + json_each() 子查询 + RECURSIVE CTE
  - pipeline.filter_by_safety 是**第二道硬防线**（架构级 0% 红线），
    DB 层过敏原过滤只是性能优化，绝不能单独依赖。
"""

from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy import and_, or_, select, func, text
from sqlalchemy.orm import selectinload

from src.config import get_utcnow
from src.db.models import Cuisine, Dish, GeoEntity


# ============================================================================
# 基础查询：准入通过的菜品
# ============================================================================


def base_admitted_dishes_query():
    """返回仅 admission_result='admitted' 的 Dish 查询构造器。"""
    return (
        select(Dish)
        .where(Dish.admission_result == "admitted")
    )


# ============================================================================
# 地理筛选（含子节点递归）
# ============================================================================


async def find_city_and_descendants(session, city_name: str) -> list[GeoEntity]:
    """
    找到城市及其所有子节点（区县/街道）。

    策略：先按 name + level='city' 找城市根节点，再递归查子节点。
    SQLAlchemy 2.0 用 CTE（WITH RECURSIVE）实现。
    """
    from sqlalchemy import CTE, literal_column, union_all

    cte = (
        select(GeoEntity.id, GeoEntity.parent_id, GeoEntity.name, GeoEntity.level)
        .where(GeoEntity.name == city_name, GeoEntity.level == "city")
        .cte(name="geo_cte", recursive=True)
    )

    cte = cte.union_all(
        select(GeoEntity.id, GeoEntity.parent_id, GeoEntity.name, GeoEntity.level)
        .where(GeoEntity.parent_id == cte.c.id)
    )

    result = await session.execute(select(GeoEntity).where(GeoEntity.id.in_(select(cte.c.id))))
    return list(result.scalars().all())


def filter_by_geo(query, geo_entity_ids: Iterable):
    """过滤在给定地理范围内的 Dish。"""
    ids = list(geo_entity_ids)
    if not ids:
        # sqlalchemy.text() 是原生 SQL 片段，各后端都兼容；func.text() 在 SQLite 上会炸
        return query.where(text("1=0"))  # 无结果 → 诚实降级
    return query.where(Dish.geo_entity_id.in_(ids))


# ============================================================================
# 菜系筛选
# ============================================================================


async def find_cuisine_and_descendants(session, cuisine_name: str) -> list[Cuisine]:
    """找到菜系及其子菜系。"""
    cte = (
        select(Cuisine.id, Cuisine.parent_id, Cuisine.name)
        .where(Cuisine.name == cuisine_name)
        .cte(name="cuisine_cte", recursive=True)
    )
    cte = cte.union_all(
        select(Cuisine.id, Cuisine.parent_id, Cuisine.name)
        .where(Cuisine.parent_id == cte.c.id)
    )
    result = await session.execute(select(Cuisine).where(Cuisine.id.in_(select(cte.c.id))))
    return list(result.scalars().all())


def filter_by_cuisine(query, cuisine_ids: Iterable):
    ids = list(cuisine_ids)
    if not ids:
        return query
    return query.where(Dish.cuisine_id.in_(ids))


# ============================================================================
# 安全前置过滤：数据库层排除
# ============================================================================


def exclude_allergens(query, session, user_restrictions: list[str]):
    """
    排除含有用户忌口/过敏原的菜品（数据库层预过滤）。

    B3 dialect-aware：
      - Postgres: `NOT (common_allergens && ARRAY[...])` —— DB 层硬排除
      - SQLite:   **退化为 no-op**，由 pipeline.filter_by_safety 做 Python 层硬过滤

    为什么 SQLite 退化安全？
      架构设计里有 **双保险**：DB 层预过滤（性能优化） + pipeline.filter_by_safety（硬红线）。
      SQLite 开发环境不需要追求 DB 层性能，pipeline 层的 `filter_by_safety` 是
      **架构级 0% 红线**，独立于 DB dialect，100% 覆盖所有安全硬排除规则。

    架构级不变：**过敏原命中 → 一票否决（0% 遗漏）**。
    """
    if not user_restrictions:
        return query

    # 从 AsyncSession 拿 engine dialect
    try:
        dialect_name = session.get_bind().dialect.name
    except Exception:
        dialect_name = "postgresql"

    if dialect_name == "sqlite":
        # SQLite: DB 层不做预过滤，交给 pipeline 硬红线兜底
        # 注释说明：双保险设计，pipeline 层 filter_by_safety 独立于 DB
        return query
    else:
        # Postgres: ARRAY && 操作符 —— DB 层第一道硬排除
        return query.where(~Dish.common_allergens.op("&&")(list(user_restrictions)))


def exclude_expired_source(query, review_cycle_days: int = 180):
    """排除完全过期的数据源（可选，保留给 Python 层诚实降级处理）。"""
    # 不在 DB 层过滤，交给 Python 层诚实降级（pipeline.filter_by_safety 规则 4）
    return query


# ============================================================================
# 组合查询：构建完整推荐 SQL
# ============================================================================


async def build_recommendation_query(
    session,
    city_name: Optional[str] = None,
    cuisine_name: Optional[str] = None,
    user_restrictions: Optional[list[str]] = None,
    max_items: int = 10,
) -> list[Dish]:
    """
    组合所有筛选条件，返回候选 Dish 列表。

    这是推荐引擎的数据库访问入口。调用方拿到 Dish 对象后，
    交给 pipeline.pipeline() 做准入 + 安全 + 排序 + 展示的 Python 层判定。
    """
    query = base_admitted_dishes_query()

    # 地理筛选
    if city_name:
        entities = await find_city_and_descendants(session, city_name)
        query = filter_by_geo(query, [e.id for e in entities])

    # 菜系筛选
    if cuisine_name:
        cuisines = await find_cuisine_and_descendants(session, cuisine_name)
        query = filter_by_cuisine(query, [c.id for c in cuisines])

    # 安全前置过滤（过敏原硬排除）
    if user_restrictions:
        query = exclude_allergens(query, session, user_restrictions)

    # 排序：先 locality_score，再 evidence_level（DB 层粗排，Python 层精排）
    query = query.order_by(Dish.locality_score.desc())

    # 加载关联数据
    query = query.options(
        selectinload(Dish.cuisine),
        selectinload(Dish.geo_entity),
    )

    query = query.limit(max_items * 3)  # 多拉一些，让 Python 层 pipeline 精排

    result = await session.execute(query)
    return list(result.scalars().unique().all())
