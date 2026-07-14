"""CLI 展示：載入範例資料、執行媒合、印出 RE 目標分析報表。

用法:
    python -m scripts.demo
"""

from __future__ import annotations

from app.data import load_sample_dataset
from app.matching import match


def _fmt(mwh: float) -> str:
    """以 GWh 呈現大數字，較易閱讀。"""
    return f"{mwh / 1000:,.1f} GWh"


def main() -> None:
    dataset = load_sample_dataset()
    result = match(dataset)

    print("=" * 68)
    print(" 台灣綠電媒合平台 — 範例情境分析")
    print("=" * 68)

    print("\n[ 風場利用情形 ]")
    print(f"{'案場':<28}{'年發電':>12}{'已分配':>12}{'利用率':>10}")
    for f in result.wind_farm_results:
        print(
            f"{f.name:<28}{_fmt(f.annual_generation_mwh):>12}"
            f"{_fmt(f.allocated_mwh):>12}{f.utilization_ratio:>9.0%}"
        )

    print("\n[ 企業 RE 目標分析 ]")
    print(
        f"{'企業':<12}{'用電':>12}{'綠電':>12}"
        f"{'覆蓋率':>9}{'RE目標':>9}{'缺口':>12}{'達標':>6}"
    )
    for c in result.company_results:
        print(
            f"{c.name:<12}{_fmt(c.annual_consumption_mwh):>12}"
            f"{_fmt(c.allocated_mwh):>12}{c.coverage_ratio:>8.0%}"
            f"{c.re_target_ratio:>8.0%}{_fmt(c.target_gap_mwh):>12}"
            f"{('達標' if c.target_met else '未達'):>6}"
        )

    s = result.summary
    print("\n[ 平台總覽 ]")
    print(f"  總發電量      : {_fmt(s.total_generation_mwh)}")
    print(f"  總分配量      : {_fmt(s.total_allocated_mwh)}")
    print(f"  剩餘綠電      : {_fmt(s.total_surplus_mwh)}")
    print(f"  綠電利用率    : {s.utilization_ratio:.0%}")
    print(f"  RE 目標總缺口 : {_fmt(s.total_target_gap_mwh)}")
    print(
        f"  達標企業數    : {s.companies_meeting_target} / {s.company_count}"
    )
    print("=" * 68)


if __name__ == "__main__":
    main()
