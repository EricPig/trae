"""配置模块导出。"""

from datetime import datetime, timezone


def get_utcnow() -> datetime:
    """F2 fix：timezone-aware UTC —— 取代已 deprecate 的 datetime.utcnow()"""
    return datetime.now(timezone.utc)


from src.config.constants import (
    ADMISSION_TABLE,
    AdmissionDecision,
    EVIDENCE_MAPPING,
    HALLUCINATION_TARGET,
    MIN_NATIVE_SCORE,
    MIN_FIRST_BREACH_YEAR,
    MAX_NATIONAL_CHAIN_SCORE,
    MAX_ADMISSION_RATE,
    MAX_CROSS_REVERSAL_RATE,
    MAX_D_CLASS_PRESS_RATE,
    PresentationTier,
    REVIEW_CYCLE_DAYS,
    S0_WEIGHT_CUISINE,
    S0_WEIGHT_NATIVE,
    S0_WEIGHT_YEARS,
    SAFETY_VIOLATION_TARGET,
    SafetyStatus,
    SOURCE_ANNOTATION_TARGET,
    NATIVE_SCORE_MAP,
    CAPABILITY_DISCLOSURE_TARGET,
)
from src.config.settings import Settings, get_settings

__all__ = [
    "Settings",
    "get_settings",
    # 常量
    "SAFETY_VIOLATION_TARGET",
    "HALLUCINATION_TARGET",
    "SOURCE_ANNOTATION_TARGET",
    "CAPABILITY_DISCLOSURE_TARGET",
    "S0_WEIGHT_NATIVE",
    "S0_WEIGHT_YEARS",
    "S0_WEIGHT_CUISINE",
    "ADMISSION_TABLE",
    "EVIDENCE_MAPPING",
    "NATIVE_SCORE_MAP",
    "REVIEW_CYCLE_DAYS",
    # 枚举
    "AdmissionDecision",
    "PresentationTier",
    "SafetyStatus",
    # 断言常量
    "MAX_NATIONAL_CHAIN_SCORE",
    "MIN_NATIVE_SCORE",
    "MIN_FIRST_BREACH_YEAR",
    "MAX_ADMISSION_RATE",
    "MAX_CROSS_REVERSAL_RATE",
    "MAX_D_CLASS_PRESS_RATE",
]
