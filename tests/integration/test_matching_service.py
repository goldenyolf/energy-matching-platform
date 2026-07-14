"""Integration tests for the DB-backed matching service."""

from __future__ import annotations

from app.models import MatchingRunStatus
from app.services import analytics_service, matching_service


def test_run_matching_persists_run_and_results(seeded_db):
    run = matching_service.run_matching(seeded_db, "2024-01")
    assert run.id is not None
    assert run.status == MatchingRunStatus.COMPLETED
    assert run.started_at is not None and run.completed_at is not None
    assert run.result_summary["total_allocated_mwh"] > 0
    assert len(run.results) > 0
    # every result row carries an auditable reason
    assert all(r.allocation_reason for r in run.results)


def test_expired_and_pending_contracts_are_skipped(seeded_db):
    run = matching_service.run_matching(seeded_db, "2024-01")
    skipped_ids = {s["contract_id"] for s in run.result_summary["skipped_contracts"]}
    # PPA-2020-007 (expired) and PPA-2025-008 (pending) must be skipped
    reasons = " ".join(s["reason"] for s in run.result_summary["skipped_contracts"])
    assert len(skipped_ids) >= 2
    assert "not active" in reasons or "ended" in reasons or "not started" in reasons


def test_allocated_never_exceeds_generation(seeded_db):
    summary = analytics_service.period_summary(seeded_db, "2024-01")
    assert summary.total_allocated_mwh <= summary.total_generation_mwh + 1e-6
    assert summary.total_unallocated_mwh >= 0


def test_undersupplied_customer_has_gap(seeded_db):
    rows = {
        c.code: c for c in analytics_service.customer_analytics(seeded_db, "2024-01")
    }
    tsmc = rows["CUST-TSMC"]
    assert tsmc.achieved_re_percent < 100
    assert tsmc.gap_to_target_mwh > 0
    assert tsmc.target_met is False


def test_small_customer_meets_target(seeded_db):
    rows = {
        c.code: c for c in analytics_service.customer_analytics(seeded_db, "2024-01")
    }
    assert rows["CUST-TCI"].target_met is True


def test_wind_farm_analytics_reports_utilization(seeded_db):
    farms = {
        f.code: f for f in analytics_service.wind_farm_analytics(seeded_db, "2024-01")
    }
    zhongtun = farms["WF-ZHONGTUN"]
    # small farm supplies more than the single small customer uses -> surplus
    assert zhongtun.unallocated_mwh > 0
    assert 0 <= zhongtun.utilization_percent <= 100


def test_contract_utilization_is_computed(seeded_db):
    rows = analytics_service.contract_utilization(seeded_db, "2024-01")
    assert len(rows) > 0
    for r in rows:
        if r.contract_limit_mwh:
            assert r.utilization_percent is not None


def test_compute_outcome_is_repeatable(seeded_db):
    a = matching_service.compute_outcome(seeded_db, "2024-01")
    b = matching_service.compute_outcome(seeded_db, "2024-01")
    assert [x.allocated_mwh for x in a.allocations] == [
        x.allocated_mwh for x in b.allocations
    ]
