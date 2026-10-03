"""
AI 推荐子系统骨架。

遵循 AI-RECOMMENDATION.md 设计：
  Layer 1: 约束提取（LLM → StructuredConstraint，不做推荐）
  Layer 2: 推荐引擎调用（通过 ACL，唯一数据通道）
  Layer 3: RAG 证据检索（数据源 + 核验时间）
  Layer 4: 诚实层（承认不确定 + 能力档位 + 商业透明）
  Layer 5: LLM 格式化（非内容生成）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ============================================================================
# 数据模型（Pydantic-free，保持轻量）
# ============================================================================


@dataclass
class StructuredConstraint:
    """用户查询/对话 → 结构化约束。Layer 1 输出。"""

    city: Optional[str] = None
    region: Optional[str] = None
    dietary_restrictions: list[str] = field(default_factory=list)
    cuisine_preference: Optional[str] = None
    scene: Optional[str] = None  # 家庭聚餐 / 朋友聚会 / 独自品尝
    time_of_day: Optional[str] = None  # 早餐 / 午餐 / 晚餐 / 夜宵
    budget_range: Optional[tuple[float, float]] = None
    exclude_chain: bool = True  # 排除连锁（默认）
    must_have_allergens_free: bool = True  # 必须无过敏原
    raw_text: str = ""  # 原始查询/对话文本

    def to_pipeline_input(self) -> dict:
        """转换为推荐引擎 pipeline 的输入格式。"""
        return {
            "city": self.city,
            "dietary_restrictions": self.dietary_restrictions,
            "cuisine_preference": self.cuisine_preference,
        }

    def is_empty(self) -> bool:
        return not any([
            self.city, self.region, self.dietary_restrictions,
            self.cuisine_preference, self.scene, self.time_of_day,
        ])


@dataclass
class EvidenceChain:
    """Layer 3 RAG 检索结果。"""

    dish_id: str
    source_name: str
    verified_at: Optional[datetime]
    completeness: str  # "complete" / "partial" / "missing"
    notes: Optional[str] = None
    has_allergy_data: bool = False
    geo_conflict: bool = False

    @property
    def is_reliable(self) -> bool:
        return self.completeness == "complete" and self.source_name is not None


@dataclass
class HonestyDeclaration:
    """Layer 4 诚实声明。"""

    capability_statement: str = ""  # 能力档位声明
    uncertainty_flags: list[str] = field(default_factory=list)  # 不确定性标记
    commercial_disclosure: str = ""  # 商业透明声明
    safe_to_proceed: bool = True  # 是否安全推荐

    @property
    def notes_to_user(self) -> list[str]:
        """展示给用户的诚实提示。"""
        out: list[str] = []
        out.extend(self.uncertainty_flags)
        if self.commercial_disclosure:
            out.append(self.commercial_disclosure)
        return out


@dataclass
class AIRecommendation:
    """AI 推荐最终输出。"""

    recommendations: list[dict]  # 含 dish_id, name, locality_score, evidence_tag
    evidence: dict[str, EvidenceChain]  # dish_id → 证据链
    honesty: HonestyDeclaration
    constraint: StructuredConstraint
    decision_log: list[str] = field(default_factory=list)
    used_recommendation_engine: bool = True  # 是否调用了推荐引擎（降级标记）
    note: str = ""  # 额外说明（降级/覆盖外等）


# ============================================================================
# ACL（Anti-Corruption Layer）— AI 与 DB 的唯一通道
# ============================================================================


class RecommendationEngineACL:
    """
    ACL：AI 子系统唯一允许的数据获取通道。

    AI 代码中绝对禁止：
      - 直接 import sqlalchemy / psycopg
      - 直接写 SQL
      - 持有数据库连接池

    这些约束在代码层 + 静态检查层共同守护（FF-ARCH-03/04）。
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine  # 推荐引擎服务实例（不是数据库！）

    async def query_recommendations(
        self, constraint: StructuredConstraint
    ) -> list[dict]:
        """
        从推荐引擎获取候选列表。

        输入：结构化约束
        输出：推荐引擎已过滤 + 排序 + 展示标记后的结果

        这里调用的是推荐引擎的服务接口，不涉及任何数据库操作。
        """
        return await self._engine.recommend(constraint.to_pipeline_input())

    async def get_evidence(self, dish_ids: list[str]) -> dict[str, EvidenceChain]:
        """
        获取菜品的证据链（RAG 用）。

        注意：这里通过内部服务接口，不是直接查 PostgreSQL。
        """
        return await self._engine.get_evidence_batch(dish_ids)


# ============================================================================
# Layer 1-5 骨架
# ============================================================================


async def layer1_extract_constraint(
    user_text: str,
    llm_client: Any,
    constraint_cache: Optional[Any] = None,
) -> StructuredConstraint:
    """
    Layer 1: 约束提取。

    用 LLM 把用户自然语言 → StructuredConstraint JSON。
    不做推荐，只做结构化提取。

    缓存：相同 query_hash 5 分钟内复用结果。
    """
    # 缓存 key = hash(用户文本)
    import hashlib

    query_hash = hashlib.sha256(user_text.encode()).hexdigest()
    if constraint_cache:
        cached = await constraint_cache.get(f"llm:constraint:{query_hash}")
        if cached:
            return StructuredConstraint(**cached)

    # 实际 LLM 调用由 llm_client 处理，这里是骨架
    # PROMPT_TEMPLATE 由调用方提供，遵循 "不生成推荐，只提取约束" 的指令
    constraint = await llm_client.extract_constraint(user_text)

    # 缓存
    if constraint_cache:
        await constraint_cache.set(f"llm:constraint:{query_hash}", constraint.__dict__, 300)

    return constraint


async def layer2_call_engine(
    constraint: StructuredConstraint,
    acl: RecommendationEngineACL,
    max_items: int = 5,
) -> tuple[list[dict], list[str]]:
    """
    Layer 2: 调用推荐引擎（通过 ACL）。

    返回：(候选列表, 决策日志)
    """
    log: list[str] = []
    try:
        candidates = await acl.query_recommendations(constraint)
        log.append(f"推荐引擎返回 {len(candidates)} 条候选")

        # 截断（展示层只取 max_items，更多作为兜底）
        shown = candidates[:max_items]
        return shown, log

    except Exception as e:
        log.append(f"推荐引擎调用失败: {e}")
        raise


async def layer3_rag_evidence(
    dish_ids: list[str],
    acl: RecommendationEngineACL,
) -> tuple[dict[str, EvidenceChain], list[str]]:
    """
    Layer 3: RAG 证据检索。

    对每个候选检索：
      - 数据源（source_name）
      - 核验时间（verified_at）
      - 过敏原字段完备度
      - 地域冲突

    检索失败 → 诚实降级标记（不编造）。
    """
    log: list[str] = []
    evidence_map = await acl.get_evidence(dish_ids)

    # 检查覆盖
    missing = [did for did in dish_ids if did not in evidence_map]
    if missing:
        log.append(f"{len(missing)} 条菜品无证据数据，将诚实降级")

    return evidence_map, log


def layer4_honesty(
    candidates: list[dict],
    evidence: dict[str, EvidenceChain],
    constraint: StructuredConstraint,
    review_cycle_days: int = 180,
) -> tuple[HonestyDeclaration, list[str], list[dict]]:
    """
    Layer 4: 诚实层。

    ① 不确定性标记
    ② 能力档位声明
    ③ 商业透明声明
    ④ 红线再次确认（虽然召回层已过滤，但防御性检查）

    返回：(诚实声明, 日志, 补充说明后的候选列表)
    """
    log: list[str] = []
    uncertainty: list[str] = []
    annotated = list(candidates)  # 浅拷贝，加 annotation 字段

    # 1. 检查覆盖度
    if not evidence:
        uncertainty.append("抱歉，目前没有足够的数据源支撑这些推荐，建议您参考其他来源")
        log.append("证据链完全缺失")

    # 2. 检查核验时效
    today = datetime.utcnow()
    for did, ev in evidence.items():
        if ev.verified_at:
            days = (today - ev.verified_at).days
            if days > review_cycle_days:
                uncertainty.append(f"有信息已超过 {review_cycle_days} 天未更新，建议电话确认")
                log.append(f"核验过期: {did} ({days} 天)")

    # 3. 检查过敏原完备度（对有忌口的用户）
    if constraint.dietary_restrictions:
        incomplete = [did for did, ev in evidence.items() if not ev.has_allergy_data]
        if incomplete:
            uncertainty.append("部分菜品的过敏原信息尚未收录，若您有严格忌口，建议电话确认")

    # 4. 能力档位声明（固定模板，不编造）
    capability = (
        "我帮您筛选了符合条件的本地美食推荐。所有推荐都带来源和核验时间，"
        "但我的能力边界是「结构化信息筛选」，不能替代专业的饮食建议。"
    )

    # 5. 商业透明
    commercial = "推荐结果可能包含平台导流链接，点击外部地图可能产生佣金"

    declaration = HonestyDeclaration(
        capability_statement=capability,
        uncertainty_flags=uncertainty,
        commercial_disclosure=commercial,
        safe_to_proceed=not bool([u for u in uncertainty if "无足够数据源" in u]),
    )

    return declaration, log, annotated


async def layer5_format(
    recommendations: AIRecommendation,
    llm_client: Any,
) -> AIRecommendation:
    """
    Layer 5: LLM 格式化（非内容生成）。

    LLM 只做：
      - 菜单风格组装
      - 依据说明的自然语言表达（五要素）
      - 诚实声明的格式化

    LLM 不做：
      - 生成新的菜品描述
      - 编造数据源
      - 编造营业时间/价格
    """
    # 实际格式化由 llm_client 处理，这里是骨架
    # PROMPT_TEMPLATE 明确 "只格式化以下 JSON，不添加任何不在 JSON 中的内容"
    formatted = await llm_client.format_response(recommendations)
    return formatted
