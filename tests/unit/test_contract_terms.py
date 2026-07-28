"""Unit tests for the shared contract-term maths."""

from __future__ import annotations

import pytest

from app.matching.contract_terms import (
    WIND_SEASONAL_SHARE,
    effective_price,
    min_offtake_mwh,
    monthly_share,
    monthly_volume_cap,
)


def test_flat_monthly_share_when_no_shape():
    assert monthly_share(None, 1) == pytest.approx(1 / 12)
    assert monthly_share([], 6) == pytest.approx(1 / 12)


def test_monthly_volume_cap_flat_and_shaped():
    assert monthly_volume_cap(1200.0, None, 3) == pytest.approx(100.0)
    shares = [3.0] + [1.0] * 11  # Jan = 3/14
    assert monthly_volume_cap(1400.0, shares, 1) == pytest.approx(1400 * 3 / 14)
    assert monthly_volume_cap(None, None, 1) is None


def test_wind_share_sums_to_one_and_is_winter_heavy():
    assert sum(WIND_SEASONAL_SHARE) == pytest.approx(1.0)
    # December (index 11) beats June (index 5) for Taiwan's NE monsoon.
    assert WIND_SEASONAL_SHARE[11] > WIND_SEASONAL_SHARE[5]


def test_effective_price_escalation():
    # no escalation / missing base year → base price unchanged
    assert effective_price(5.0, None, 2024, 2030) == pytest.approx(5.0)
    assert effective_price(5.0, 2.0, None, 2030) == pytest.approx(5.0)
    # 2% for 3 years
    assert effective_price(5.0, 2.0, 2024, 2027) == pytest.approx(5.0 * 1.02**3)
    # years before the base are clamped to the base price
    assert effective_price(5.0, 2.0, 2024, 2022) == pytest.approx(5.0)


def test_min_offtake_floor():
    assert min_offtake_mwh(100.0, 80.0) == pytest.approx(80.0)
    assert min_offtake_mwh(100.0, None) == 0.0
    assert min_offtake_mwh(None, 80.0) == 0.0
