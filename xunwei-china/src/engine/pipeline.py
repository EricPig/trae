"""推荐引擎 · 准入层 + 安全过滤层 + 排序层 + 展示层。

架构设计遵循 ADR-001 和基线清单 §8：
  - 准入层：二维条件（locality_level × cuisine_evidence_level + 差异化阈值）
  - 安全层：召回层硬过滤（过敏原/忌口/幻觉风险 → 一票否决）
  - 排序层：locality_score 单标量（60/25/15 权重表）
  - 展示层：四象限规则矩阵
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.config import (
    ADMISSION_TABLE,
    AdmissionDecision,
    EVIDENCE_MAPPING,
    NATIVE_SCORE_MAP,
    PresentationTier,
    S0_WEIGHT_CUISINE,
    S0_WEIGHT_NATIVE,
    S0_WEIGHT_YEARS,
    SafetyStatus,
)


# ============================================================================
# Locality Score 计算（S0 权重表 · 基线清单回归断言守护）
# ============================================================================


def compute_locality_score(
    locality_level: str,
    evidence_level: str,
    establishment_year: Optional[int],
) -> tuple[float, float, float, float]:
    """
    计算 locality_score + 三因子。

    返回:
      (score, native_score, years_factor, cuisine_factor)

    公式: score = 0.60 × native_score + 0.25 × years_factor + 0.15 × cuisine_factor

    注意：
      - 这是 S0 权重表，修改需要架构师审批 + 跑基线脚本验证
      - 断言 R1: national_chain 最高 < 50
      - 断言 R2/R3: native 最低 ≥ 60（S0 下 native_score 恒 100，60×0.6 + 其他 ≥ 60）
      - 断言 R5: first_breach_year ≥ 92
    """
    # native_score
    native_score = NATIVE_SCORE_MAP.get(locality_level, 50.0)

    # years_factor（开业年限因子：0 → 80 年插值封顶 100）
    if establishment_year is None or establishment_year <= 0:
        years_factor = 50.0  # 未知给中性分
    elif establishment_year >= 80:
        years_factor = 100.0
    else:
        years_factor = 50.0 + (establishment_year / 80.0) * 50.0

    # cuisine_factor（证据等级 + 地域支持）
    evidence_base = {"A": 90.0, "B": 75.0, "C": 60.0, "D": 45.0}.get(evidence_level, 50.0)
    # 地域本地性加权：native 类型证据等级更高权重
    if locality_level == "native":
        cuisine_factor = evidence_base
    elif locality_level == "localized":
        cuisine_factor = evidence_base * 0.85
    else:  # national_chain
        cuisine_factor = evidence_base * 0.5

    score = (
        S0_WEIGHT_NATIVE * native_score
        + S0_WEIGHT_YEARS * years_factor
        + S0_WEIGHT_CUISINE * cuisine_factor
    )
    return score, native_score, years_factor, cuisine_factor


# ============================================================================
# 准入层（二维准入表 · 基线清单 §8）
# ============================================================================


@dataclass
class AdmissionResult:
    decision: AdmissionDecision
    threshold: float
    actual_score: float
    reason: str
    ui_note: Optional[str] = None


def adjudicate_admission(
    locality_level: str,
    evidence_level: str,
    locality_score: float,
) -> AdmissionResult:
    """
    准入判定。唯一使用二维准入表的地方。

    规则（基线清单 §8）：
      - native: 全等级 threshold=60
      - localized: A/B=60, C=55(资料较少), D=50(仅商家自述)
      - national_chain: 一律排除
    """
    key = (locality_level, evidence_level)

    # national_chain 一律排除
    if key[0] == "national_chain":
        return AdmissionResult(
            decision=AdmissionDecision.EXCLUDED_CHAIN,
            threshold=float("inf"),
            actual_score=locality_score,
            reason="全国连锁，不在地方特色推荐范围内",
        )

    row = ADMISSION_TABLE.get(key)
    if row is None:
        # 未知组合，保守排除
        return AdmissionResult(
            decision=AdmissionDecision.MISSING_DATA,
            threshold=60.0,
            actual_score=locality_score,
            reason="准入表缺失此组合",
        )

    threshold = row["threshold"]
    ui_note = row.get("ui_note")

    if locality_score >= threshold:
        return AdmissionResult(
            decision=AdmissionDecision.ADMITTED,
            threshold=threshold,
            actual_score=locality_score,
            reason=f"达到准入阈值 {threshold}",
            ui_note=ui_note,
        )
    else:
        return AdmissionResult(
            decision=AdmissionDecision.BELOW_THRESHOLD,
            threshold=threshold,
            actual_score=locality_score,
            reason=f"低于准入阈值 {threshold}",
            ui_note=ui_note,
        )


# ============================================================================
# 安全硬过滤层（召回层 · 架构级常量 0%）
# ============================================================================


@dataclass
class SafetyResult:
    status: SafetyStatus
    reason: str
    is_excluded: bool  # 是否从候选集排除


def filter_by_safety(
    allergens: list[str],
    allergen_data_complete: bool,
    user_restrictions: list[str],
    has_evidence_source: bool,
    verified_at: Optional[datetime],
    review_cycle_days: int = 180,
) -> SafetyResult:
    """
    安全过滤。在召回层（候选集形成前）执行。

    规则：
      1. 过敏原/忌口 命中 → 排除（一票否决）
      2. 过敏原信息缺失 + 用户有忌口 → 诚实降级（标记，让上层决定）
      3. 无数据源支撑 → 排除（幻觉风险）
      4. 核验时间 > review_cycle_days → 诚实降级
    """
    # 规则 3：无数据源 → 幻觉风险
    if not has_evidence_source:
        return SafetyResult(
            status=SafetyStatus.HALLUCINATION_RISK,
            reason="无数据源支撑，存在事实幻觉风险",
            is_excluded=True,
        )

    # 规则 1：过敏原硬命中
    if user_restrictions:
        restricted = set(r.lower() for r in user_restrictions)
        hit = [a for a in allergens if a.lower() in restricted]
        if hit:
            return SafetyResult(
                status=SafetyStatus.FILTERED_ALLERGEN,
                reason=f"命中忌口/过敏原: {', '.join(hit)}",
                is_excluded=True,
            )

    # 规则 2：过敏原信息缺失 + 用户有忌口 → 诚实降级（但不排除，让上层决定）
    if user_restrictions and not allergen_data_complete:
        return SafetyResult(
            status=SafetyStatus.DATA_MISSING,
            reason="过敏原信息不完备，建议电话确认",
            is_excluded=False,
        )

    # 规则 4：核验过期
    if verified_at is not None:
        days_old = (datetime.utcnow() - verified_at).days
        if days_old > review_cycle_days:
            return SafetyResult(
                status=SafetyStatus.DATA_MISSING,
                reason=f"核验时间已过期（{days_old} 天前，建议电话确认）",
                is_excluded=False,
            )

    return SafetyResult(
        status=SafetyStatus.CLEAR,
        reason="安全检查通过",
        is_excluded=False,
    )


# ============================================================================
# 展示层 · 四象限规则（基线清单 §1.5 裁决 1）
# ============================================================================


def resolve_presentation(
    admission_result: AdmissionResult,
    evidence_level: str,
    locality_score: float,
) -> PresentationTier:
    """
    四象限规则矩阵：

                  本地性高（≥60）       本地性低（<60）
    资料 🟢 高    最佳推荐位            排序降权（兜底）
    资料 🟡 中    重点扶持位            普通位
    资料 🔴 低    禁降权/禁折叠/必优先   唯一允许折叠
    """
    if admission_result.decision != AdmissionDecision.ADMITTED:
        return PresentationTier.STANDARD

    high_locality = locality_score >= 60.0
    evidence_tag = EVIDENCE_MAPPING.get(evidence_level, "🟡")

    if high_locality:
        if evidence_tag == "🔴":
            return PresentationTier.PRIORITY_WITH_NOTE  # 护城河保护
        return PresentationTier.BEST
    else:
        if evidence_tag == "🔴":
            return PresentationTier.FOLDED  # 唯一允许折叠
        return PresentationTier.STANDARD


# ============================================================================
# 完整的推荐条目（四合一判定结果）
# ============================================================================


@dataclass
class Recommendation:
    """单条菜品的推荐判定结果。"""

    dish_id: str
    name: str
    locality_level: str
    evidence_level: str

    # 四个层的判定
    admission: AdmissionResult
    safety: SafetyResult
    locality_score: float
    presentation: PresentationTier

    # 展示辅助
    evidence_tag: str = ""
    source_name: str = ""
    verified_at: Optional[datetime] = None

    # 调试：每一层的判定日志
    decision_log: list[str] = field(default_factory=list)

    @property
    def is_admitted(self) -> bool:
        return self.admission.decision == AdmissionDecision.ADMITTED

    @property
    def is_safe(self) -> bool:
        return not self.safety.is_excluded

    @property
    def will_be_shown(self) -> bool:
        return self.is_admitted and self.is_safe


# ============================================================================
# 流水线：对候选集执行准入 → 安全 → 排序 → 展示
# ============================================================================


def pipeline(
    candidates: list[dict],
    user_restrictions: Optional[list[str]] = None,
) -> list[Recommendation]:
    """
    完整推荐流水线。

    输入: 候选菜品列表（字典）
    输出: Recommendation 对象列表，已按四象限 + 排序优先级组织

    注意：这是**同步函数**，无 IO，方便测试和缓存。IO 部分由调用方（服务层）处理。
    """
    restrictions = user_restrictions or []
    results: list[Recommendation] = []

    for c in candidates:
        decision_log: list[str] = []

        # 计算 locality_score（若输入未预计算）
        if "locality_score" not in c or c["locality_score"] is None:
            score, native, years, cuisine = compute_locality_score(
                c.get("locality_level", "native"),
                c.get("evidence_level", "C"),
                c.get("establishment_year"),
            )
        else:
            score = c["locality_score"]
            native = c.get("native_score", 0)
            years = c.get("years_factor", 0)
            cuisine = c.get("cuisine_factor", 0)

        # 准入判定
        admission = adjudicate_admission(
            c.get("locality_level", "native"),
            c.get("evidence_level", "C"),
            score,
        )
        decision_log.append(f"[准入] {admission.decision.value}: {admission.reason}")

        # 安全过滤（只对准入通过的做，效率）
        if admission.decision == AdmissionDecision.ADMITTED:
            safety = filter_by_safety(
                allergens=c.get("common_allergens", []),
                allergen_data_complete=c.get("allergen_info_complete", False),
                user_restrictions=restrictions,
                has_evidence_source=bool(c.get("source_name")),
                verified_at=c.get("verified_at"),
            )
        else:
            safety = SafetyResult(
                status=SafetyStatus.CLEAR,
                reason="未通过准入，跳过安全检查",
                is_excluded=False,
            )
        decision_log.append(f"[安全] {safety.status.value}: {safety.reason}")

        # 展示层
        presentation = resolve_presentation(
            admission, c.get("evidence_level", "C"), score
        )
        decision_log.append(f"[展示] {presentation.value}")

        evidence_tag = EVIDENCE_MAPPING.get(c.get("evidence_level", "C"), "🟡")

        results.append(
            Recommendation(
                dish_id=str(c.get("id", "")),
                name=c.get("name", ""),
                locality_level=c.get("locality_level", "native"),
                evidence_level=c.get("evidence_level", "C"),
                admission=admission,
                safety=safety,
                locality_score=score,
                presentation=presentation,
                evidence_tag=evidence_tag,
                source_name=c.get("source_name", ""),
                verified_at=c.get("verified_at"),
                decision_log=decision_log,
            )
        )

    # 过滤：只保留已准入且安全的
    shown = [r for r in results if r.will_be_shown]

    # 排序：先按展示层级（BEST > PRIORITY_WITH_NOTE > STANDARD > FOLDED），再按 locality_score
    tier_order = {
        PresentationTier.BEST: 0,
        PresentationTier.PRIORITY_WITH_NOTE: 1,  # 注意：优先但不压 BEST
        PresentationTier.STANDARD: 2,
        PresentationTier.FOLDED: 3,
    }
    shown.sort(key=lambda r: (tier_order.get(r.presentation, 99), -r.locality_score))

    return shown
