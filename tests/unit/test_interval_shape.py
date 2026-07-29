"""Tests for interval aggregation helpers (B6)."""

from __future__ import annotations

from datetime import date

import pytest

from app.matching import interval_shape as ish


def test_days_in_period_inclusive():
    assert ish.days_in_period(date(2024, 1, 1), date(2024, 1, 31)) == 31
    assert ish.days_in_period(date(2024, 2, 1), date(2024, 2, 29)) == 29


def test_hour_of_day_sums_groups_by_hour():
    # 2 days, 24 hours each; value = hour index, second day doubled.
    series = [float(h) for h in range(24)] + [float(h) * 2 for h in range(24)]
    out = ish.hour_of_day_sums(series, ndays=2)
    assert len(out) == 24
    assert out[3] == pytest.approx(3 + 6)  # day0 hour3 + day1 hour3
    assert out[0] == pytest.approx(0.0)


def test_heatmap_cfe_is_matched_over_consumption_per_cell():
    ndays = 2
    matched = [0.0] * 48
    con = [0.0] * 48
    # day0 hour5: 6/10 -> 60%
    matched[0 * 24 + 5] = 6.0
    con[0 * 24 + 5] = 10.0
    # day1 hour5: 3/10 -> 30%
    matched[1 * 24 + 5] = 3.0
    con[1 * 24 + 5] = 10.0
    hm = ish.heatmap_cfe(matched, con, ndays)
    assert len(hm) == 2 and len(hm[0]) == 24
    assert hm[0][5] == pytest.approx(60.0)
    assert hm[1][5] == pytest.approx(30.0)
    assert hm[0][0] == pytest.approx(0.0)  # zero consumption -> 0, no divide error
