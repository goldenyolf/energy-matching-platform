"""End-to-end: Taipower adapter rows import cleanly through csv_importer,
and scripts.seed can build the adapter as a selectable source.
"""

from __future__ import annotations

import pytest

from app.ingestion import csv_importer
from app.ingestion.sources import CsvDataSource
from app.ingestion.taipower import TaipowerWindSource
from app.models import GenerationData, WindFarm
from tests.unit.test_taipower_source import CSV_HEADER, CSV_ROWS


@pytest.fixture
def csv_file(tmp_path):
    path = tmp_path / "wind_turbines.csv"
    content = CSV_HEADER + "\n" + "\n".join(CSV_ROWS) + "\n"
    path.write_bytes(("﻿" + content).encode("utf-8"))
    return path


def test_taipower_rows_import_into_db(db, csv_file):
    src = TaipowerWindSource(year=2024, csv_path=csv_file)

    wf_result = csv_importer.import_wind_farms(db, src.wind_farms())
    gen_result = csv_importer.import_generation(db, src.generation())

    assert wf_result.errors == []
    assert gen_result.errors == []

    farms = {w.code: w for w in db.query(WindFarm).all()}
    assert set(farms) == {"TPC-TEST", "TPC-OTHER"}

    gens = db.query(GenerationData).filter_by(wind_farm_id=farms["TPC-TEST"].id).all()
    by_start = {g.period_start.isoformat(): g.generated_energy_mwh for g in gens}
    assert by_start["2024-01-01"] == pytest.approx(3000.0)
    assert by_start["2024-02-01"] == pytest.approx(500.0)
    assert "2024-03-01" not in by_start  # all-missing month dropped


def test_build_source_selects_adapter():
    from scripts.seed import build_source

    taipower = build_source("taipower", year=2024, fetch=False)
    assert isinstance(taipower, TaipowerWindSource)

    sample = build_source("sample", year=2024, fetch=False)
    assert isinstance(sample, CsvDataSource)
