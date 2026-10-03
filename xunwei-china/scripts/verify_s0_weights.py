"""
基线清单回归断言（§7）。

断言 R1–R5：locality_score 权重表和准入表的正确性。
任何一条失败 = 架构被破坏 = 禁止合并。

用法：
    python -m scripts.verify_s0_weights
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Optional

from src.config import (
    S0_WEIGHT_CUISINE,
    S0_WEIGHT_NATIVE,
    S0_WEIGHT_YEARS,
    MAX_NATIONAL_CHAIN_SCORE,
    MIN_NATIVE_SCORE,
)
from src.engine.pipeline import compute_locality_score


# ============================================================================
# 断言 R1-R5 实现
# ============================================================================


def _score(year: Optional[int]) -> float:
    """计算 native 类型某开业年份的 locality_score。"""
    s, *_ = compute_locality_score("native", "C", year)
    return s


@dataclass
class AssertionResult:
    name: str
    passed: bool
    detail: str


def run_assertions() -> list[AssertionResult]:
    results: list[AssertionResult] = []

    # R1: 任意 national_chain locality_score < 50
    def r1() -> AssertionResult:
        max_score = 0.0
        for ev in ["A", "B", "C", "D"]:
            for year in [None, 0, 20, 40, 60, 80]:
                s, *_ = compute_locality_score("national_chain", ev, year)
                max_score = max(max_score, s)
        passed = max_score < MAX_NATIONAL_CHAIN_SCORE
        return AssertionResult("R1 连锁最高分 < 50", passed, f"实测最高 {max_score:.2f}")

    # R2: 任意 native 且 ≤20 年 ≥ 60
    def r2() -> AssertionResult:
        min_score = float("inf")
        for ev in ["A", "B", "C", "D"]:
            for year in [None, 0, 10, 20]:
                s, *_ = compute_locality_score("native", ev, year)
                min_score = min(min_score, s)
        passed = min_score >= MIN_NATIVE_SCORE
        return AssertionResult("R2 native ≤20年 ≥ 60", passed, f"实测最低 {min_score:.2f}")

    # R3: native + C/D + ≥20 年 ≥ 60（隐藏款保护）
    def r3() -> AssertionResult:
        min_score = float("inf")
        for ev in ["C", "D"]:
            for year in [20, 40, 60, 80]:
                s, *_ = compute_locality_score("native", ev, year)
                min_score = min(min_score, s)
        passed = min_score >= MIN_NATIVE_SCORE
        return AssertionResult("R3 native + C/D + ≥20年 ≥ 60", passed, f"实测最低 {min_score:.2f}")

    # R4: 改变年限不得使 native 跌破 60
    def r4() -> AssertionResult:
        min_score = float("inf")
        # 全区间扫描：10–55 岁 native + D 级（最敏感的组合）
        for year in range(1, 81):
            s, *_ = compute_locality_score("native", "D", year)
            min_score = min(min_score, s)
        passed = min_score >= MIN_NATIVE_SCORE
        return AssertionResult("R4 native 全区间 ≥ 60", passed, f"实测最低 {min_score:.2f}")

    # R5: 超老连锁越线年份 first_breach_year ≥ 92
    def r5() -> AssertionResult:
        breach_year = None
        for year in range(80, 150):
            s, *_ = compute_locality_score("national_chain", "A", year)
            if s >= 60.0:
                breach_year = year
                break
        # 实际：national_chain 上限 40.0（native_score=30，远低于阈值）
        # 断言是显式声明 + 数值校验双重守护
        passed = breach_year is None or breach_year >= 92
        detail = f"越线年份 {breach_year}" if breach_year else "未越线（安全）"
        return AssertionResult("R5 连锁越线年 ≥ 92", passed, detail)

    for check in (r1, r2, r3, r4, r5):
        results.append(check())

    return results


# ============================================================================
# 主入口
# ============================================================================


def main() -> int:
    print("=" * 60)
    print("基线清单回归断言 R1–R5")
    print("=" * 60)

    all_passed = True
    for r in run_assertions():
        symbol = "✅" if r.passed else "❌"
        print(f"  {symbol} {r.name}: {r.detail}")
        if not r.passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("✅ 全部断言通过")
        return 0
    else:
        print("❌ 断言失败！架构被破坏！")
        print("   → 检查 S0 权重表、准入表、或 locality_score 计算逻辑")
        print("   → 修改后必须重新运行此脚本 + data_metrics_calc_exp.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
