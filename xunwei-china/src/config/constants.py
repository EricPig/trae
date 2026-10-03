"""寻味中国 · 架构级常量（不可修改，硬编码）"""

from __future__ import annotations

from enum import Enum
from typing import Final


# ============================================================================
# 🔴 红线 / 架构常量（这些值是架构设计的基石，修改需架构师审批）
# ============================================================================

# 过敏原违反率目标 = 0%（一票否决）
SAFETY_VIOLATION_TARGET: Final[float] = 0.0
# 门店事实幻觉率目标 = 0%（一票否决）
HALLUCINATION_TARGET: Final[float] = 0.0
# 来源标注率目标 = 100%
SOURCE_ANNOTATION_TARGET: Final[float] = 100.0
# 能力档位披露率目标 = 100%
CAPABILITY_DISCLOSURE_TARGET: Final[float] = 100.0

# ============================================================================
# 排序层 S0 权重表（60/25/15）—— 基线清单回归断言守护
# ============================================================================
# 本地性 = 0.60 × native_score + 0.25 × years_factor + 0.15 × cuisine_factor
# 注意：这是硬编码，不得在配置文件中修改
S0_WEIGHT_NATIVE: Final[float] = 0.60
S0_WEIGHT_YEARS: Final[float] = 0.25
S0_WEIGHT_CUISINE: Final[float] = 0.15

# 本地性等级对应的 native_score
NATIVE_SCORE_MAP: Final[dict[str, float]] = {
    "native": 100.0,       # 本土
    "localized": 70.0,     # 本地化连锁
    "national_chain": 30.0,  # 全国连锁（上限 40，排除线 < 60）
}

# ============================================================================
# 二维准入表（基线清单 §8，唯一可行解）
# ============================================================================
ADMISSION_TABLE: Final[dict[tuple[str, str], dict]] = {
    # (locality_level, evidence_level) -> {threshold, ui_note}
    ("native", "A"): {"threshold": 60, "ui_note": None},
    ("native", "B"): {"threshold": 60, "ui_note": None},
    ("native", "C"): {"threshold": 60, "ui_note": None},
    ("native", "D"): {"threshold": 60, "ui_note": None},
    ("localized", "A"): {"threshold": 60, "ui_note": None},
    ("localized", "B"): {"threshold": 60, "ui_note": None},
    ("localized", "C"): {"threshold": 55, "ui_note": "资料较少"},
    ("localized", "D"): {"threshold": 50, "ui_note": "仅商家自述，建议电话确认"},
    ("national_chain", "*"): {"threshold": float("inf"), "ui_note": None, "exclude": True},
}

# ============================================================================
# 展示层四象限规则
# ============================================================================
# evidence_strength × locality_score → presentation
# 🔴 = 资料有限，🟡 = 资料一般，🟢 = 资料充足
EVIDENCE_MAPPING: Final[dict[str, str]] = {
    "A": "🟢",
    "B": "🟢",
    "C": "🟡",
    "D": "🔴",
}


class AdmissionDecision(str, Enum):
    """准入判定结果。"""

    ADMITTED = "admitted"
    EXCLUDED_CHAIN = "excluded_chain"  # national_chain 直接排除
    BELOW_THRESHOLD = "below_threshold"
    MISSING_DATA = "missing_data"


class PresentationTier(str, Enum):
    """展示层四象限 —— 基线清单 §1.5 裁决 1。"""

    BEST = "best"                   # 🟢/🟡 + 高本地性 → 最佳推荐位
    PRIORITY_WITH_NOTE = "priority" # 🔴 + 高本地性 → 禁降权禁折叠必优先
    STANDARD = "standard"           # 其他普通
    FOLDED = "folded"               # 🔴 + 低本地性 → 唯一允许折叠


class SafetyStatus(str, Enum):
    """安全过滤层判定。"""

    CLEAR = "clear"                  # 安全通过
    FILTERED_ALLERGEN = "filtered"   # 命中用户忌口/过敏原 → 排除
    DATA_MISSING = "data_missing"    # 安全相关数据缺失 → 诚实降级
    HALLUCINATION_RISK = "risk"      # 无数据源支撑 → 排除


# ============================================================================
# 回归断言常量（基线清单 §7）
# ============================================================================

# 断言 R1: national_chain locality_score < 50
MAX_NATIONAL_CHAIN_SCORE: Final[float] = 50.0

# 断言 R2/R3: native locality_score >= 60
MIN_NATIVE_SCORE: Final[float] = 60.0

# 断言 R5: first_breach_year >= 92
MIN_FIRST_BREACH_YEAR: Final[int] = 92


# ============================================================================
# 适应度函数阈值（基线清单）
# ============================================================================

# FF-ADJ-01: 准入率 ≤ 88%
MAX_ADMISSION_RATE: Final[float] = 88.0
# FF-ADJ-02: 交叉反转率 ≤ 12%
MAX_CROSS_REVERSAL_RATE: Final[float] = 12.0
# FF-SCR-03: D 级被压过率（分层监控 3a=5.7%, 3c=9.2%, 上界 12%）
MAX_D_CLASS_PRESS_RATE: Final[float] = 12.0


# ============================================================================
# 验证时效
# ============================================================================
REVIEW_CYCLE_DAYS: Final[int] = 180  # 条目核验时效 180 天（基线清单 §6）
