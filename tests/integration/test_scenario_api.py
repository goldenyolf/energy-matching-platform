"""API test for GET /api/v1/matching/scenario (greenfield what-if explorer)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models import ConsumptionData, Contract, Customer, GenerationData, WindFarm
from app.models.enums import ContractStatus, GreenTargetType


@pytest.fixture()
def seeded(db):
    # Two farms, two customers, but only ONE contract (F1↔K1). The scenario
    # explorer can still pair F2 with anyone (hypothetical).
    f1 = WindFarm(
        code="F1", name="F1", installed_capacity_mw=100, feed_in_price_per_kwh=4.0
    )
    f2 = WindFarm(
        code="F2", name="F2", installed_capacity_mw=100, feed_in_price_per_kwh=4.2
    )
    k1 = Customer(
        code="K1",
        company_name="K1",
        re_target_percent=50.0,
        green_target_type=GreenTargetType.RE_PERCENT,
    )
    k2 = Customer(
        code="K2",
        company_name="K2",
        re_target_percent=50.0,
        green_target_type=GreenTargetType.RE_PERCENT,
    )
    db.add_all([f1, f2, k1, k2])
    db.flush()
    db.add_all(
        [
            GenerationData(
                wind_farm_id=f1.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=100.0,
            ),
            GenerationData(
                wind_farm_id=f2.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                generated_energy_mwh=100.0,
            ),
            ConsumptionData(
                customer_id=k1.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                consumed_energy_mwh=100.0,
            ),
            ConsumptionData(
                customer_id=k2.id,
                period_start=date(2024, 1, 1),
                period_end=date(2024, 1, 31),
                consumed_energy_mwh=100.0,
            ),
            Contract(
                contract_number="C1",
                wind_farm_id=f1.id,
                customer_id=k1.id,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 12, 31),
                status=ContractStatus.ACTIVE,
                priority=100,
                contracted_percentage=100.0,
                price_per_kwh=4.5,
            ),
        ]
    )
    db.commit()
    return {"f1": f1.id, "f2": f2.id, "k1": k1.id, "k2": k2.id}


def test_scenario_returns_full_structure(client, seeded):
    resp = client.get("/api/v1/matching/scenario", params={"period": "2024-01"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["solver_status"] == "Optimal"
    assert body["assumed_transfer_price_per_kwh"] == 5.0
    assert set(body["farm_ids"]) == {seeded["f1"], seeded["f2"]}
    assert set(body["customer_ids"]) == {seeded["k1"], seeded["k2"]}
    # has_contract must be a bool, and True ONLY for the real PPA pair (F1↔K1);
    # a hypothetical pair is never mislabeled as a real contract.
    real_pairs = {(seeded["f1"], seeded["k1"])}
    for a in body["allocations"]:
        assert isinstance(a["has_contract"], bool)
        if a["has_contract"]:
            assert (a["wind_farm_id"], a["customer_id"]) in real_pairs
    # both customers are served, so at least one hypothetical pairing appears
    assert any(not a["has_contract"] for a in body["allocations"])


def test_scenario_filters_farms(client, seeded):
    # Restrict to F2 only → F1 must not appear.
    resp = client.get(
        "/api/v1/matching/scenario",
        params={"period": "2024-01", "farm_ids": str(seeded["f2"])},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["farm_ids"] == [seeded["f2"]]
    farms_in_alloc = {a["wind_farm_id"] for a in body["allocations"]}
    assert seeded["f1"] not in farms_in_alloc


def test_scenario_re_target_override(client, seeded):
    # Override K1's RE target to 100% → its target energy is the full 100 MWh.
    resp = client.get(
        "/api/v1/matching/scenario",
        params={"period": "2024-01", "re_targets": f"{seeded['k1']}:100"},
    )
    assert resp.status_code == 200
    body = resp.json()
    k1t = {t["customer_id"]: t for t in body["customer_targets"]}[seeded["k1"]]
    assert k1t["re_target_mwh"] == pytest.approx(100.0)
    assert k1t["re_target_met"] is True


def test_scenario_feed_in_override_flips_farm_preference(client, seeded):
    def farm_alloc(body, fid):
        return sum(
            a["allocated_mwh"] for a in body["allocations"] if a["wind_farm_id"] == fid
        )

    # Default: F1 (feed-in 4.0) is cheaper than F2 (4.2) → F1 carries the green.
    base = client.get("/api/v1/matching/scenario", params={"period": "2024-01"}).json()
    assert farm_alloc(base, seeded["f1"]) > farm_alloc(base, seeded["f2"])

    # Override F1's feed-in to 5.0 (now pricier than F2) → preference flips to F2.
    over = client.get(
        "/api/v1/matching/scenario",
        params={"period": "2024-01", "feed_ins": f"{seeded['f1']}:5.0"},
    ).json()
    assert farm_alloc(over, seeded["f2"]) > farm_alloc(over, seeded["f1"])


def test_scenario_rejects_bad_re_target(client, seeded):
    resp = client.get(
        "/api/v1/matching/scenario",
        params={"period": "2024-01", "re_targets": "notanumber"},
    )
    assert resp.status_code == 422
