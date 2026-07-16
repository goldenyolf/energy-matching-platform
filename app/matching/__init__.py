"""Green energy matching engine (pure, deterministic, DB-agnostic)."""

from app.matching.engine import (
    Allocation,
    ContractInput,
    CustomerDemand,
    CustomerSummary,
    FarmSummary,
    FarmSupply,
    MatchingOutcome,
    SkippedContract,
    build_customer_summary,
    build_farm_summary,
    match_period,
)
from app.matching.optimizer import (
    CustomerTarget,
    OptimizationOutcome,
    OptimizeOptions,
    optimize_period,
)

__all__ = [
    "Allocation",
    "ContractInput",
    "CustomerDemand",
    "CustomerSummary",
    "CustomerTarget",
    "FarmSupply",
    "FarmSummary",
    "MatchingOutcome",
    "OptimizationOutcome",
    "OptimizeOptions",
    "SkippedContract",
    "build_customer_summary",
    "build_farm_summary",
    "match_period",
    "optimize_period",
]
