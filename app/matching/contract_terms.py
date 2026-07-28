"""Shared contract-term maths: monthly volume shape, take-or-pay floor, and
CPI price escalation. Used by the engine, optimizer, settlement and risk so the
rules stay identical everywhere.

``contracted_energy_mwh`` on a contract is an **annual** volume. The monthly cap
is that annual volume times the month's share of the year. With no custom shape
the share is a flat 1/12; a contract may instead carry ``monthly_shares`` (12
weights, any positive scale) — e.g. the winter-heavy Taiwan wind curve below.
"""

from __future__ import annotations

# Taiwan onshore wind is winter-heavy (NE monsoon). Same shape as the demo
# generation profile; normalised to sum to 1.0 for use as monthly volume shares.
_WIND_WEIGHTS = [1.35, 1.25, 1.05, 0.85, 0.70, 0.55, 0.55, 0.60, 0.85, 1.15, 1.30, 1.40]
_WIND_TOTAL = sum(_WIND_WEIGHTS)
WIND_SEASONAL_SHARE: list[float] = [w / _WIND_TOTAL for w in _WIND_WEIGHTS]


def _valid_shares(shares: list[float] | None) -> list[float] | None:
    """Return 12 positive-sum weights, or None to fall back to a flat 1/12."""
    if not shares or len(shares) != 12:
        return None
    total = sum(s or 0.0 for s in shares)
    if total <= 0:
        return None
    return [max(0.0, s or 0.0) for s in shares]


def monthly_share(shares: list[float] | None, month: int) -> float:
    """Fraction of the annual volume that falls in ``month`` (1–12).

    Flat 1/12 when no valid custom shape is given; otherwise the month's weight
    divided by the sum of weights."""
    valid = _valid_shares(shares)
    if valid is None:
        return 1.0 / 12.0
    return valid[month - 1] / sum(valid)


def monthly_volume_cap(
    annual_mwh: float | None, shares: list[float] | None, month: int
) -> float | None:
    """The month's slice of an annual contracted volume (None = uncapped)."""
    if annual_mwh is None:
        return None
    return annual_mwh * monthly_share(shares, month)


def effective_price(
    base_price: float,
    escalation_percent: float | None,
    base_year: int | None,
    period_year: int,
) -> float:
    """Contract price for ``period_year`` after annual CPI escalation.

    ``base_price × (1 + esc)^(period_year − base_year)``. No escalation (or a
    missing base year) returns the base price unchanged; years before the base
    are clamped to the base price."""
    if not escalation_percent or base_year is None:
        return base_price
    years = period_year - base_year
    if years <= 0:
        return base_price
    return base_price * (1.0 + escalation_percent / 100.0) ** years


def min_offtake_mwh(
    monthly_cap: float | None, min_offtake_percent: float | None
) -> float:
    """Take-or-pay floor for a month: ``monthly_cap × percent`` (0 when unset)."""
    if not min_offtake_percent or monthly_cap is None:
        return 0.0
    return monthly_cap * min_offtake_percent / 100.0
