"""T-REC certificate lifecycle: issue+transfer from matching, retire, ledger."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Contract, Customer, TrecBatch, WindFarm
from app.models.enums import TrecStatus
from app.schemas.trec import TrecBatchOut, TrecLedger, TrecSummary
from app.services.matching_service import compute_outcome


def issue_for_period(db: Session, period: str) -> int:
    """Idempotent: create a transferred batch per (farm, customer) from matching."""
    outcome = compute_outcome(db, period)
    contracts = {c.id: c for c in db.execute(select(Contract)).scalars()}
    farms = {f.id: f for f in db.execute(select(WindFarm)).scalars()}
    custs = {c.id: c for c in db.execute(select(Customer)).scalars()}
    existing = {
        (b.wind_farm_id, b.customer_id)
        for b in db.execute(
            select(TrecBatch).where(TrecBatch.period == period)
        ).scalars()
    }

    qty: dict[tuple[int, int], float] = defaultdict(float)
    for a in outcome.allocations:
        if a.allocated_mwh <= 1e-9:
            continue
        c = contracts.get(a.contract_id)
        if c is None:
            continue
        qty[(c.wind_farm_id, c.customer_id)] += a.allocated_mwh

    created = 0
    for (farm_id, cust_id), q in qty.items():
        if (farm_id, cust_id) in existing:
            continue
        fc = farms[farm_id].code if farm_id in farms else farm_id
        cc = custs[cust_id].code if cust_id in custs else cust_id
        db.add(
            TrecBatch(
                batch_no=f"TREC-{period}-{fc}-{cc}",
                wind_farm_id=farm_id,
                customer_id=cust_id,
                period=period,
                quantity_mwh=round(q, 3),
                status=TrecStatus.TRANSFERRED.value,
            )
        )
        created += 1
    db.commit()
    return created


def retire(db: Session, batch_id: int) -> TrecBatch:
    b = db.get(TrecBatch, batch_id)
    if b is None:
        raise NotFoundError(f"T-REC batch {batch_id} not found")
    b.status = TrecStatus.RETIRED.value
    db.commit()
    db.refresh(b)
    return b


def batch_to_out(b: TrecBatch) -> TrecBatchOut:
    return TrecBatchOut(
        id=b.id,
        batch_no=b.batch_no,
        wind_farm_code=b.wind_farm.code,
        wind_farm_name=b.wind_farm.name,
        customer_code=b.customer.code,
        company_name=b.customer.company_name,
        period=b.period,
        quantity_mwh=round(b.quantity_mwh, 3),
        status=b.status,
    )


def get_ledger(
    db: Session, period: str | None = None, customer_id: int | None = None
) -> TrecLedger:
    stmt = select(TrecBatch)
    if period:
        stmt = stmt.where(TrecBatch.period == period)
    if customer_id:
        stmt = stmt.where(TrecBatch.customer_id == customer_id)
    batches = list(db.execute(stmt.order_by(TrecBatch.id.desc())).scalars())

    transferred = [b for b in batches if b.status == TrecStatus.TRANSFERRED.value]
    retired = [b for b in batches if b.status == TrecStatus.RETIRED.value]
    t_mwh = round(sum(b.quantity_mwh for b in transferred), 3)
    r_mwh = round(sum(b.quantity_mwh for b in retired), 3)
    return TrecLedger(
        period=period,
        summary=TrecSummary(
            total_batches=len(batches),
            total_quantity_mwh=round(t_mwh + r_mwh, 3),
            transferred_mwh=t_mwh,
            retired_mwh=r_mwh,
            transferred_batches=len(transferred),
            retired_batches=len(retired),
        ),
        batches=[batch_to_out(b) for b in batches],
    )
