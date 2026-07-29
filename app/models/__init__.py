"""ORM models. Importing this package registers all tables on ``Base``."""

from app.models.battery import Battery
from app.models.consumption import ConsumptionData
from app.models.contract import Contract
from app.models.customer import Customer
from app.models.enums import (
    ContractStatus,
    MatchingRunStatus,
    TrecStatus,
    WindFarmStatus,
)
from app.models.generation import GenerationData
from app.models.interval import IntervalReading
from app.models.matching import MatchingResult, MatchingRun
from app.models.meter import Meter
from app.models.trec import TrecBatch
from app.models.wind_farm import WindFarm

__all__ = [
    "Battery",
    "ConsumptionData",
    "Contract",
    "ContractStatus",
    "Customer",
    "GenerationData",
    "IntervalReading",
    "MatchingResult",
    "MatchingRun",
    "MatchingRunStatus",
    "Meter",
    "TrecBatch",
    "TrecStatus",
    "WindFarm",
    "WindFarmStatus",
]
