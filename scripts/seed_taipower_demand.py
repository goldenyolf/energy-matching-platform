"""Seed monthly consumption aligned to the Taipower generation window.

The demo customers only carry 2024 consumption, but the real Taipower generation
covers a rolling recent-12-months window (e.g. 2025-06 .. 2026-05). Without
demand in those months the matching engine allocates nothing there (a customer
never receives more than it consumed that month). This loader gives each customer
a deterministic monthly consumption (annual / 12) for exactly the months that
have Taipower generation in the DB, so TPC- farms actually participate.

It derives the window from the data already in the DB (not a fixed date range),
so it stays aligned as the rolling window moves, and is idempotent per
(customer, period) — re-running skips months a customer already has.

Run after seeding the Taipower farms/generation and the demo customers::

    python -m scripts.seed --source taipower --fetch
    python -m scripts.seed_taipower_demand
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, create_all
from app.models import ConsumptionData, Customer, GenerationData

DATA_SOURCE = "taipower-window"


def seed_demand(db: Session) -> int:
    """Create consumption for each customer over every Taipower generation period.

    Returns the number of consumption rows created.
    """
    periods = db.execute(
        select(GenerationData.period_start, GenerationData.period_end)
        .where(GenerationData.data_source == "taipower")
        .distinct()
    ).all()
    customers = db.execute(select(Customer)).scalars().all()

    created = 0
    for customer in customers:
        monthly = round((customer.annual_consumption_mwh or 0.0) / 12.0, 2)
        for period_start, period_end in periods:
            exists = db.execute(
                select(ConsumptionData.id).where(
                    ConsumptionData.customer_id == customer.id,
                    ConsumptionData.period_start == period_start,
                )
            ).first()
            if exists:
                continue
            db.add(
                ConsumptionData(
                    customer_id=customer.id,
                    period_start=period_start,
                    period_end=period_end,
                    consumed_energy_mwh=monthly,
                    data_source=DATA_SOURCE,
                )
            )
            created += 1
    db.commit()
    return created


def main() -> None:
    create_all()
    db = SessionLocal()
    try:
        created = seed_demand(db)
        print(f"taipower-window consumption: created={created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
