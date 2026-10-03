"""
元数据路由 —— 地理发现 / 菜系列表 / 能力档位 / 数据源透明 / 红线详情 / 推荐统计。

产品全案 §3.9 E2–E5 期待：
  帮我做决定（Top3 收敛）· 说出依据（五要素）· 记住我是谁（画像）·
  懂我的场景（结构化输入）· 敢承认不知道（诚实拒答 + 能力档位）

架构不变量公开（红线透明）：
  - 过敏原违反率目标 = 0%    → SAFETY_VIOLATION_TARGET
  - 门店事实幻觉率目标 = 0%   → HALLUCINATION_TARGET
  - 来源标注率目标 = 100%    → SOURCE_ANNOTATION_TARGET
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.connection import get_db_session
from src.db.models import Cuisine, DataSource, Dish, GeoEntity
from src.config import (
    SAFETY_VIOLATION_TARGET,
    HALLUCINATION_TARGET,
    SOURCE_ANNOTATION_TARGET,
    CAPABILITY_DISCLOSURE_TARGET,
    ADMISSION_TABLE,
)

router = APIRouter(prefix="/api", tags=["meta"])


# ============================================================================
# 1. 诚实能力档位声明（产品全案 §3.9 E5）
# ============================================================================


@router.get("/meta/capability")
async def capability_statement():
    """
    诚实能力档位声明 —— 任何时候用户想知道"这个 AI 能做什么、不能做什么"都应该能找到。

    固定模板，不编造。
    """
    return {
        "name": "寻味中国 AI",
        "statement": (
            "我是「寻味中国」的推荐助手。我能帮你在指定城市"
            "按你的口味、忌口、场景条件筛选本地美食推荐。"
            "所有推荐都带来源和核验时间。"
            "但我不知道的地方就说不知道，不编造，不瞎推荐。"
        ),
        "levels": [
            {
                "level": 0,
                "name": "我不知道的地方就说不知道",
                "description": "诚实拒答比瞎推荐好。不编造菜品、不编造数据源、不编造营业时间。",
                "enforced_by": [
                    "ACL 阻止 AI 直连 DB",
                    "RAG 强制检索（必须有数据源支撑）",
                    "无数据源 → 排除（不进候选集）",
                ],
            },
            {
                "level": 1,
                "name": "结构化筛选（非个性化推荐）",
                "description": "根据你提供的条件（城市、忌口、菜系、场景）筛选本地美食。",
                "limitation": (
                    "我不用你的历史行为做「个性化推荐」—— 因为那会引入"
                    "不可解释的排序黑盒。我的推荐是**条件筛选的结果**，"
                    "每一条都能说出「为什么是这条」。"
                ),
                "engine": "推荐引擎准入层 + 安全层 + 排序层 + 展示层（四层流水线）",
            },
            {
                "level": 2,
                "name": "AI 对话 + 诚实格式化",
                "description": (
                    "我可以理解自然语言对话，帮你收敛到 Top3 推荐。"
                    "但 AI 只做「格式化」和「条件结构化」，"
                    "真正的推荐逻辑是确定性的四层流水线。"
                ),
                "ai_boundaries": [
                    "AI 不直接生成菜品描述",
                    "AI 不编造数据源或核验时间",
                    "AI 不做最终排序（排序由 locality_score 决定）",
                    "AI 最多 4 轮对话收敛（架构约束）",
                ],
            },
        ],
        "can_do": [
            "在一个城市内，根据你的条件（忌口、菜系、预算）筛选本地美食",
            "对每条推荐给出依据（技法、食材来源、历史背景、适合场景）",
            "记住你的忌口和偏好（可选，默认客户端本地存储）",
            "告诉你每条推荐的信息来源和核验时间",
            "帮你对话式收敛到 Top3 推荐",
        ],
        "cannot_do": [
            "我不保证门店当前营业状态",
            "我不提供实时价格",
            "我不替代专业的饮食医疗建议",
            "我不做商户评分排名（只关注菜品本身）",
            "我不做隐藏式个性化推荐（所有排序可解释）",
        ],
        "red_lines": {
            "allergen_violation_target_pct": SAFETY_VIOLATION_TARGET,
            "hallucination_target_pct": HALLUCINATION_TARGET,
            "source_annotation_target_pct": SOURCE_ANNOTATION_TARGET,
            "capability_disclosure_target_pct": CAPABILITY_DISCLOSURE_TARGET,
            "note": "这些是架构级常量，运行时由适应度函数 FF-SAFE-01/02 和 FF-DATA-01 守护",
        },
        "commercial_disclosure": (
            "我们的推荐结果可能包含平台导流链接，点击外部地图可能产生佣金。"
            "推荐层与导流层物理隔离，导流信号不影响推荐排序（架构红线）。"
        ),
        "version": "0.1.0",
    }


# ============================================================================
# 2. 红线详情页（架构级常量公开透明）
# ============================================================================


@router.get("/meta/red-lines")
async def red_lines_detail():
    """
    架构红线详情 —— 产品的不可妥协边界。

    这些是架构设计时就写死在代码里的常量（src/config/constants.py），
    不是配置文件中可修改的参数。修改需要架构师审批。
    """
    return {
        "allergen_zero": {
            "name": "过敏原违反率 = 0%",
            "value": SAFETY_VIOLATION_TARGET,
            "enforcement": [
                "召回层硬过滤 —— 过敏原命中的菜品不进入候选集（一票否决）",
                "Python 层 filter_by_safety() 第二道防线",
                "数据层 ARRAY && 预排除（src/db/queries.py exclude_allergens）",
                "每日扫描 + 架构断言守护",
            ],
            "why_zero": (
                "过敏是致命错误（轻则不适，重则休克）。"
                "宁可漏推荐也不能错推荐过敏原风险。"
            ),
            "source": "产品全案 §2.5 一票否决",
        },
        "hallucination_zero": {
            "name": "门店事实幻觉率 = 0%",
            "value": HALLUCINATION_TARGET,
            "enforcement": [
                "ACL（Anti-Corruption Layer）阻止 AI 直连 DB",
                "RAG 强制检索 —— 每条推荐必须有数据源支撑",
                "无数据源 → 排除（SafetyStatus.HALLUCINATION_RISK）",
                "AI 不生成内容，只格式化",
            ],
            "why_zero": (
                "幻觉型错误比数据缺失更危险 —— 编造的信息会让用户做出错误决策。"
                "宁可不推荐也不瞎推荐。"
            ),
            "source": "AI-RECOMMENDATION.md",
        },
        "source_annotation_100": {
            "name": "来源标注率 = 100%",
            "value": SOURCE_ANNOTATION_TARGET,
            "enforcement": [
                "Dish 表 schema 强制 source_name NOT NULL",
                "DATA-01 适应度函数（缺失数据源率 → 触发告警）",
                "展示层必须渲染 source_name + verified_at",
            ],
            "why_100": (
                "可核验是产品的核心差异化。没有来源的「本地美食推荐」和大众点评没区别。"
            ),
            "source": "基线清单 §1.1 差异化策略",
        },
        "constants_locations": {
            "config_file": "src/config/constants.py",
            "pre_commit_guard": "scripts/verify_s0_weights.py（R1-R5 回归断言）",
            "architecture_docs": "/architecture/",
        },
    }


# ============================================================================
# 3. 数据源透明（Data Source Transparency）
# ============================================================================


@router.get("/meta/sources")
async def list_data_sources(
    session: AsyncSession = Depends(get_db_session),
):
    """
    数据源列表 + 许可证 —— 用户知道我们的数据从哪来、能用在什么场景。

    产品全案 §3.9 N3 不信任点：用户对「AI 数据从哪来」存疑。
    这个端点直接打消疑虑 —— 全部公开。
    """
    result = await session.execute(select(DataSource).order_by(DataSource.verified_at.desc()))
    sources = list(result.scalars().all())

    # 按许可证分组
    by_license: dict[str, list[dict]] = {}
    for s in sources:
        lic = s.license_type or "unknown"
        by_license.setdefault(lic, []).append({
            "name": s.name,
            "url": s.url,
            "verified_at": s.verified_at.isoformat(),
            "commercial_use_allowed": s.commercial_use_allowed,
        })

    return {
        "total_sources": len(sources),
        "by_license_type": {
            lic: {"count": len(items), "sources": items}
            for lic, items in by_license.items()
        },
        "note": (
            "所有数据源都经过许可证审计。"
            "商用数据标注 commercial_use_allowed=true。"
            "用户生成内容（UGC）不进入数据源列表 —— 只作为参考证据。"
        ),
    }


# ============================================================================
# 4. 数据完整性仪表盘（诚实层支撑）
# ============================================================================


@router.get("/meta/data-integrity")
async def data_integrity_dashboard(
    review_cycle_days: int = 180,
    session: AsyncSession = Depends(get_db_session),
):
    """
    数据完整性仪表盘 —— 告诉用户「我们的数据覆盖度如何」。

    这是诚实层的关键支撑：
      - 过敏原信息完整度 → 有忌口用户会关心
      - 核验时效 → 超过 180 天未核验 → 诚实降级提示
      - 证据等级分布 → A/B/C/D 各占多少

    不返回敏感明细数据，只返回聚合统计。
    """
    total_result = await session.execute(select(func.count(Dish.id)))
    total = total_result.scalar() or 0

    admitted_result = await session.execute(
        select(func.count(Dish.id)).where(Dish.admission_result == "admitted")
    )
    admitted = admitted_result.scalar() or 0

    # 过敏原完整度
    allergen_complete = await session.execute(
        select(func.count(Dish.id)).where(Dish.allergen_info_complete.is_(True))
    )
    allergen_done = allergen_complete.scalar() or 0

    # 核验时效
    cutoff = datetime.utcnow()
    result = await session.execute(
        select(
            func.count(Dish.id).label("total"),
            func.count(Dish.id).filter(Dish.verified_at > cutoff).label("with_verified"),
            func.count(Dish.id).filter(
                Dish.verified_at < cutoff - func.cast(f"{review_cycle_days} days", type_=None)
            ).label("expired"),
        )
    )
    stats = result.one()

    # 证据等级分布
    ev_dist = await session.execute(
        select(Dish.cuisine_evidence_level, func.count(Dish.id))
        .group_by(Dish.cuisine_evidence_level)
        .order_by(Dish.cuisine_evidence_level)
    )
    evidence_distribution = {row[0]: row[1] for row in ev_dist.all()}

    return {
        "total_dishes": total,
        "admitted_dishes": admitted,
        "admission_rate_pct": round(admitted / total * 100, 1) if total else 0,
        "integrity": {
            "allergen_data_complete_pct": round(allergen_done / total * 100, 1) if total else 0,
            "admission_rate_pct": round(admitted / total * 100, 1) if total else 0,
        },
        "evidence_distribution": evidence_distribution,
        "review_cycle_days": review_cycle_days,
        "what_this_means": (
            "过敏原数据完整度 = 我们有多少菜品明确标注了过敏原信息。"
            "证据等级 A = 来源权威且多重交叉验证，D = 仅单一来源（商家自述/UGC）。"
            "超过 180 天未核验的菜品会在展示层诚实降级为「建议电话确认」。"
        ),
    }


# ============================================================================
# 5. 推荐引擎可视化（四象限分布 + 准入表）
# ============================================================================


@router.get("/meta/recommendation-engine")
async def recommendation_engine_visualization():
    """
    推荐引擎四象限可视化 + 二维准入表 —— 让前端画出「寻味中国的推荐地图」。

    这是产品的差异化展示点：
      - 用户可以看到自己在哪个象限
      - 🔴 + 高本地性 → 禁折叠禁降权（护城河）
      - 四象限规则是架构层写死的，不是机器学习黑盒
    """
    # 二维准入表转 JSON（inf → "never" 字符串，保持 JSON 可序列化）
    import math
    admission_table_json = {}
    for (loc, ev), row in ADMISSION_TABLE.items():
        key = f"{loc}|{ev}"
        threshold = row.get("threshold")
        if isinstance(threshold, float) and math.isinf(threshold):
            threshold_str = "never"  # national_chain → 永远排除
        else:
            threshold_str = threshold
        admission_table_json[key] = {
            "locality_level": loc,
            "evidence_level": ev,
            "threshold": threshold_str,
            "ui_note": row.get("ui_note"),
            "exclude": row.get("exclude", False),
        }

    return {
        "layers": [
            {
                "name": "准入层（二维条件）",
                "inputs": ["locality_level", "cuisine_evidence_level"],
                "output": "admitted / excluded_chain / below_threshold / missing_data",
                "data": admission_table_json,
                "why_two_dimensional": (
                    "基线清单 §8 证明单标量排序无法同时保护隐藏款和淘汰连锁。"
                    "861 组 Pareto 穷举无可行解 —— 唯一解法是两层分离。"
                ),
            },
            {
                "name": "安全层（召回层硬过滤）",
                "inputs": ["allergens_complete", "user_restrictions", "has_evidence_source"],
                "output": "clear / filtered / data_missing / hallucination_risk",
                "rules": [
                    "过敏原命中 → 排除（一票否决）",
                    "无数据源支撑 → 排除（幻觉风险）",
                    "过敏原信息缺失 + 用户有忌口 → 诚实降级",
                ],
            },
            {
                "name": "排序层（单标量）",
                "inputs": ["native_score", "years_factor", "cuisine_factor"],
                "output": "locality_score（0-100）",
                "formula": "score = 0.60 × native_score + 0.25 × years_factor + 0.15 × cuisine_factor",
                "weights_source": "基线清单回归断言 R1-R5",
            },
            {
                "name": "展示层（四象限）",
                "inputs": ["locality_score", "evidence_tag"],
                "output": "best / priority / standard / folded",
                "rules": [
                    "🟢 + 高本地性 → 最佳推荐位",
                    "🟡 + 高本地性 → 重点扶持位",
                    "🔴 + 高本地性 → 禁降权禁折叠（护城河）",
                    "🔴 + 低本地性 → 唯一允许折叠的象限",
                ],
            },
        ],
        "architecture_assertions": {
            "R1": {
                "name": "连锁 locality_score < 50",
                "meaning": "全国连锁永远无法进入本地美食推荐",
            },
            "R2_R3_R4": {
                "name": "native 全区间 ≥ 60",
                "meaning": "本土菜品永远能通过准入（哪怕资料有限）",
            },
            "R5": {
                "name": "连锁越线年份 ≥ 92",
                "meaning": "即使有一家百年连锁，它依然在本地美食的定义之外",
            },
        },
    }


# ============================================================================
# 6. 地理 / 菜系 / 过敏原（之前已有的端点保持不变）
# ============================================================================


@router.get("/meta/cities")
async def list_cities(
    limit: int = 50,
    session: AsyncSession = Depends(get_db_session),
):
    """已覆盖的城市列表 + 菜品数统计。"""
    from sqlalchemy import select as sa_select

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
async def list_cuisines(session: AsyncSession = Depends(get_db_session)):
    """菜系列表（含子菜系层级）。"""
    result = await session.execute(select(Cuisine).order_by(Cuisine.name))
    cuisines = list(result.scalars().all())

    # 构建层级树
    by_id = {c.id: {"id": str(c.id), "name": c.name, "children": []} for c in cuisines}
    roots = []
    for c in cuisines:
        if c.parent_id and c.parent_id in by_id:
            by_id[c.parent_id]["children"].append(by_id[c.id])
        else:
            roots.append(by_id[c.id])

    return {
        "cuisines_flat": [{"name": c.name, "id": str(c.id)} for c in cuisines],
        "cuisines_tree": roots,
        "total": len(cuisines),
    }


@router.get("/meta/allergen-types")
async def list_allergen_types():
    """常见过敏原类型（供 UI 多选）。T0 阶段静态列表。"""
    common = [
        {"name": "花生", "severity": "high", "medical_note": "可致过敏性休克"},
        {"name": "牛奶", "severity": "high", "medical_note": "乳制品过敏 / 乳糖不耐"},
        {"name": "鸡蛋", "severity": "high"},
        {"name": "虾/海鲜", "severity": "high", "medical_note": "含壳类过敏"},
        {"name": "大豆", "severity": "medium"},
        {"name": "小麦/麸质", "severity": "medium", "medical_note": "乳糜泻"},
        {"name": "坚果", "severity": "high", "medical_note": "可致过敏性休克"},
        {"name": "辣椒", "severity": "low", "medical_note": "通常非过敏，仅对消化道敏感者有影响"},
    ]
    return {
        "common": common,
        "selectable": True,
        "note": (
            "这里是常见过敏原参考列表。实际过敏原信息以每条菜品"
            "标注的数据为准。如果你有特殊过敏，请在画像中填写详细信息。"
        ),
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
        "next_milestone": "T1 数据接入 + LLM 集成",
    }
