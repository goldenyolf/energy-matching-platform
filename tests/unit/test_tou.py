"""Unit tests for time-of-use slot/season helpers."""

from __future__ import annotations

import pytest

from app.matching.tou import GREY_TOU_PRICES, SLOT_ORDER, grey_price, season_of
from app.models.enums import Season, TimeSlot


@pytest.mark.parametrize(
    "month, expected",
    [
        (5, Season.NON_SUMMER),
        (6, Season.SUMMER),
        (9, Season.SUMMER),
        (10, Season.NON_SUMMER),
    ],
)
def test_season_of_boundaries(month, expected):
    assert season_of(month) == expected


def test_slot_order_is_peak_first():
    assert SLOT_ORDER == (TimeSlot.PEAK, TimeSlot.HALF_PEAK, TimeSlot.OFF_PEAK)


def test_grey_price_summer_peak_is_highest():
    summer_peak = grey_price(Season.SUMMER, TimeSlot.PEAK)
    summer_off = grey_price(Season.SUMMER, TimeSlot.OFF_PEAK)
    assert summer_peak > summer_off
    # every (season, slot) combination is defined
    assert len(GREY_TOU_PRICES) == len(Season) * len(TimeSlot)
