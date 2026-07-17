"""Time-of-use helpers: season derivation, slot order, TOU grey reference prices.

Season follows Taipower's summer window (Jun 1 – Sep 30). Grey prices are
illustrative demo values (NTD/kWh) roughly matching Taipower's high-voltage
time-of-use tariff magnitudes; they are configurable in real use.
"""

from __future__ import annotations

from app.models.enums import Season, TimeSlot

SLOT_ORDER: tuple[TimeSlot, ...] = (
    TimeSlot.PEAK,
    TimeSlot.HALF_PEAK,
    TimeSlot.OFF_PEAK,
)

GREY_TOU_PRICES: dict[tuple[Season, TimeSlot], float] = {
    (Season.SUMMER, TimeSlot.PEAK): 5.0,
    (Season.SUMMER, TimeSlot.HALF_PEAK): 3.5,
    (Season.SUMMER, TimeSlot.OFF_PEAK): 1.8,
    (Season.NON_SUMMER, TimeSlot.PEAK): 4.7,
    (Season.NON_SUMMER, TimeSlot.HALF_PEAK): 3.4,
    (Season.NON_SUMMER, TimeSlot.OFF_PEAK): 1.7,
}


def season_of(month: int) -> Season:
    """Taipower summer months are June through September (6–9)."""
    return Season.SUMMER if 6 <= month <= 9 else Season.NON_SUMMER


def grey_price(season: Season, slot: TimeSlot) -> float:
    return GREY_TOU_PRICES[(season, slot)]
