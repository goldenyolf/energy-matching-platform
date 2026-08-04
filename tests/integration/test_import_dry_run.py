"""Dry-run 必須跑真正的寫入路徑，然後不留任何痕跡。"""

from __future__ import annotations

from sqlalchemy import select

from app.ingestion.pipeline import dry_run_session
from app.models import Customer
from app.schemas.customer import CustomerCreate
from app.services import customers as customer_svc


def _payload(code: str) -> CustomerCreate:
    return CustomerCreate(
        code=code,
        company_name=code,
        annual_consumption_mwh=1.0,
        re_target_percent=10.0,
    )


def test_dry_run_leaves_no_trace(db):
    customer_svc.create(db, _payload("C-REAL"))

    with dry_run_session(db) as scoped:
        customer_svc.create(scoped, _payload("C-DRY"))
        inside = scoped.execute(select(Customer.code)).scalars().all()

    assert "C-DRY" in inside, "dry-run 之內應該看得到自己寫的資料"
    after = db.execute(select(Customer.code)).scalars().all()
    assert after == ["C-REAL"], f"dry-run 洩漏到真實資料庫: {after}"


def test_outer_session_still_writable_after_dry_run(db):
    with dry_run_session(db) as scoped:
        customer_svc.create(scoped, _payload("C-DRY"))

    customer_svc.create(db, _payload("C-AFTER"))
    codes = sorted(db.execute(select(Customer.code)).scalars().all())
    assert codes == ["C-AFTER"]


def test_failed_row_does_not_poison_the_rest(db):
    """單列失敗後，同一 session 仍能繼續寫入後面的列（Postgres 的必要條件）。"""
    done: list[str] = []
    with dry_run_session(db) as scoped:
        for code in ["A", "BAD", "C"]:
            nested = scoped.begin_nested()
            try:
                if code == "BAD":
                    raise ValueError("simulated")
                customer_svc.create(scoped, _payload(code))
                done.append(code)
            except ValueError:
                if nested.is_active:
                    nested.rollback()
    assert done == ["A", "C"]
