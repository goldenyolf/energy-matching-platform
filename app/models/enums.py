"""Domain enumerations."""

from __future__ import annotations

from enum import StrEnum


class WindFarmStatus(StrEnum):
    PLANNING = "planning"
    UNDER_CONSTRUCTION = "under_construction"
    OPERATIONAL = "operational"
    DECOMMISSIONED = "decommissioned"


class ContractStatus(StrEnum):
    PENDING = "pending"  # signed but not yet started
    ACTIVE = "active"  # currently in force
    EXPIRED = "expired"  # past end date
    TERMINATED = "terminated"  # cancelled early


class MatchingRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GreenTargetType(StrEnum):
    RE_PERCENT = "re_percent"
    ENERGY = "energy"


class TimeSlot(StrEnum):
    PEAK = "peak"
    HALF_PEAK = "half_peak"
    OFF_PEAK = "off_peak"


class Season(StrEnum):
    SUMMER = "summer"
    NON_SUMMER = "non_summer"


class TrecStatus(StrEnum):
    TRANSFERRED = "transferred"  # issued + transferred to the customer (bundled 轉供)
    RETIRED = "retired"  # retired by the customer to claim RE (not re-tradable)
