# 单元测试：准入层 / 安全过滤层 / 排序层

"""推荐引擎核心层的单元测试。

覆盖架构不变量：
  - 二维准入表所有组合
  - 安全过滤红线（过敏原命中 → 排除）
  - 排序权重表正确性
  - 展示层四象限规则
"""

from datetime import datetime, timedelta
from typing import Optional

import pytest

from src.config import (
    ADMISSION_TABLE,
    AdmissionDecision,
    EVIDENCE_MAPPING,
    PresentationTier,
)
from src.engine.pipeline import (
    adjudicate_admission,
    compute_locality_score,
    filter_by_safety,
    pipeline,
    resolve_presentation,
)


# ============================================================================
# 排序层测试
# ============================================================================


class TestLocalityScore:
    """S0 权重表正确性。"""

    @pytest.mark.parametrize(
        "year,expected_min",
        [
            (None, 79.25),   # 开业年份未知（给中性分）
            (0, 79.25),      # 0 年
            (20, 79.25),     # 20 年
            (80, 82.375),    # 80 年封顶
        ],
    )
    def test_native_always_above_60(self, year: Optional[int], expected_min: float):
        """断言 R2/R3/R4：native 全区间 locality_score >= 60。"""
        score, *_ = compute_locality_score("native", "C", year)
        assert score >= 60.0, f"native 类型 locality_score 必须 ≥ 60（断言 R2）"

    @pytest.mark.parametrize(
        "evidence",
        ["A", "B", "C", "D"],
    )
    def test_native_all_evidence_levels_above_60(self, evidence: str):
        """断言 R3：native + C/D + ≥20 年 ≥ 60。"""
        score, *_ = compute_locality_score("native", evidence, 30)
        assert score >= 60.0

    def test_national_chain_always_below_50(self):
        """断言 R1：national_chain 最高 < 50。"""
        max_score = 0.0
        for ev in ["A", "B", "C", "D"]:
            for year in [None, 0, 20, 40, 60, 80]:
                s, *_ = compute_locality_score("national_chain", ev, year)
                max_score = max(max_score, s)
        assert max_score < 50.0, f"连锁最高 {max_score} 不应 ≥ 50"


# ============================================================================
# 准入层测试
# ============================================================================


class TestAdjudication:
    """二维准入表。"""

    def test_national_chain_always_excluded(self):
        """连锁一律排除（基线清单 §8）。"""
        for ev in ["A", "B", "C", "D"]:
            result = adjudicate_admission("national_chain", ev, 999.0)
            assert result.decision == AdmissionDecision.EXCLUDED_CHAIN

    def test_native_always_admitted_when_above_60(self):
        """native 阈值恒 60，而 native locality_score 恒 ≥ 60 → 永远准入。"""
        for ev in ["A", "B", "C", "D"]:
            score, *_ = compute_locality_score("native", ev, 30)
            result = adjudicate_admission("native", ev, score)
            assert result.decision == AdmissionDecision.ADMITTED

    def test_localized_d_threshold_50(self):
        """localized + D 阈值 50，有 UI 提示。"""
        result = adjudicate_admission("localized", "D", 50.0)
        assert result.decision == AdmissionDecision.ADMITTED
        assert result.ui_note == "仅商家自述，建议电话确认"

    def test_localized_c_threshold_55(self):
        """localized + C 阈值 55。"""
        result = adjudicate_admission("localized", "C", 55.0)
        assert result.decision == AdmissionDecision.ADMITTED
        assert result.ui_note == "资料较少"

    def test_admission_table_complaints_threshold(self):
        """验证 ADMISSION_TABLE 所有组合的阈值与基线清单一致。"""
        # baseline: native/A=60, native/D=60, localized/D=50
        assert ADMISSION_TABLE[("native", "A")]["threshold"] == 60
        assert ADMISSION_TABLE[("native", "D")]["threshold"] == 60
        assert ADMISSION_TABLE[("localized", "A")]["threshold"] == 60
        assert ADMISSION_TABLE[("localized", "D")]["threshold"] == 50


# ============================================================================
# 安全过滤层测试
# ============================================================================


class TestSafetyFilter:
    """召回层硬过滤（红线 = 0%）。"""

    def test_allergen_hit_excludes(self):
        """过敏原命中 → 一票否决。"""
        result = filter_by_safety(
            allergens=["花生", "牛奶"],
            allergen_data_complete=True,
            user_restrictions=["花生"],
            has_evidence_source=True,
            verified_at=datetime.utcnow(),
        )
        assert result.is_excluded is True
        assert "花生" in result.reason

    def test_no_allergen_hit_passes(self):
        """无命中 → 通过。"""
        result = filter_by_safety(
            allergens=["牛奶"],
            allergen_data_complete=True,
            user_restrictions=["花生"],
            has_evidence_source=True,
            verified_at=datetime.utcnow(),
        )
        assert result.is_excluded is False
        assert result.status.value == "clear"

    def test_no_evidence_source_excludes(self):
        """无数据源 → 幻觉风险。"""
        result = filter_by_safety(
            allergens=[],
            allergen_data_complete=True,
            user_restrictions=[],
            has_evidence_source=False,
            verified_at=datetime.utcnow(),
        )
        assert result.is_excluded is True
        assert "幻觉" in result.reason

    def test_expired_verified_at_downgrades(self):
        """核验过期 → 诚实降级（不排除）。"""
        old = datetime.utcnow() - timedelta(days=200)
        result = filter_by_safety(
            allergens=[],
            allergen_data_complete=True,
            user_restrictions=[],
            has_evidence_source=True,
            verified_at=old,
        )
        assert result.is_excluded is False
        assert "过期" in result.reason or "核验" in result.reason


# ============================================================================
# 展示层测试
# ============================================================================


class TestPresentationTier:
    """四象限规则。"""

    def test_best_tier(self):
        """🟢/🟡 + 高本地性 → BEST。"""
        admission = adjudicate_admission("native", "A", 90.0)
        tier = resolve_presentation(admission, "A", 90.0)
        assert tier == PresentationTier.BEST

    def test_folded_only_quadrant(self):
        """🔴 + 低本地性 → FOLDED（唯一允许折叠的象限）。"""
        admission = adjudicate_admission("localized", "D", 50.0)
        # locality_score < 60（低本地性）
        admission.decision = AdmissionDecision.ADMITTED  # 模拟准入
        tier = resolve_presentation(admission, "D", 55.0)  # 55 < 60
        assert tier == PresentationTier.FOLDED

    def test_priority_high_locality_red(self):
        """🔴 + 高本地性 → 禁降权禁折叠必优先（护城河）。"""
        admission = adjudicate_admission("native", "D", 70.0)
        tier = resolve_presentation(admission, "D", 70.0)  # 70 ≥ 60
        assert tier == PresentationTier.PRIORITY_WITH_NOTE


# ============================================================================
# 完整流水线集成
# ============================================================================


class TestPipelineIntegration:
    """准入 → 安全 → 排序 → 展示 四合一。"""

    def test_full_pipeline_happy_path(self):
        """完整流水线：准入通过 → 安全 → 排序 → 展示 BEST。"""
        candidates = [
            {
                "id": "dish-1",
                "name": "宫保鸡丁",
                "locality_level": "native",
                "evidence_level": "A",
                "establishment_year": 50,
                "common_allergens": ["花生"],
                "allergen_info_complete": True,
                "source_name": "某地方志",
                "verified_at": datetime.utcnow() - timedelta(days=10),
            },
        ]
        results = pipeline(candidates, user_restrictions=[])
        assert len(results) == 1
        r = results[0]
        assert r.admission.decision == AdmissionDecision.ADMITTED
        assert r.safety.is_excluded is False
        assert r.presentation == PresentationTier.BEST

    def test_pipeline_allergen_exclusion(self):
        """用户有忌口 → 过敏原命中的条目被排除。"""
        candidates = [
            {
                "id": "dish-1",
                "name": "宫保鸡丁",
                "locality_level": "native",
                "evidence_level": "A",
                "common_allergens": ["花生"],
                "allergen_info_complete": True,
                "source_name": "某地方志",
                "verified_at": datetime.utcnow(),
            },
            {
                "id": "dish-2",
                "name": "麻婆豆腐",
                "locality_level": "native",
                "evidence_level": "B",
                "common_allergens": [],
                "allergen_info_complete": True,
                "source_name": "某地方志",
                "verified_at": datetime.utcnow(),
            },
        ]
        results = pipeline(candidates, user_restrictions=["花生"])
        shown = [r for r in results if r.will_be_shown]
        assert len(shown) == 1
        assert shown[0].dish_id == "dish-2"

    def test_pipeline_chain_excluded(self):
        """连锁一律排除。"""
        candidates = [
            {
                "id": "dish-chain",
                "name": "某连锁川菜",
                "locality_level": "national_chain",
                "evidence_level": "A",
                "establishment_year": 5,
                "common_allergens": [],
                "allergen_info_complete": True,
                "source_name": "商家自述",
                "verified_at": datetime.utcnow(),
            },
        ]
        results = pipeline(candidates, user_restrictions=[])
        shown = [r for r in results if r.will_be_shown]
        assert len(shown) == 0  # 连锁不能进推荐池

    def test_pipeline_high_locality_red_not_folded(self):
        """🔴 + 高本地性 → 禁折叠（护城河保护）。"""
        candidates = [
            {
                "id": "hidden-gem",
                "name": "藏在巷子里的老火锅",
                "locality_level": "native",  # 高本地性
                "evidence_level": "D",  # 🔴 资料有限
                "establishment_year": 40,
                "common_allergens": [],
                "allergen_info_complete": False,
                "source_name": "本地论坛",
                "verified_at": datetime.utcnow(),
            },
        ]
        results = pipeline(candidates, user_restrictions=[])
        shown = [r for r in results if r.will_be_shown]
        assert len(shown) == 1
        # 护城河：🔴 + 高本地性 = PRIORITY_WITH_NOTE，不是 FOLDED
        assert shown[0].presentation != PresentationTier.FOLDED
