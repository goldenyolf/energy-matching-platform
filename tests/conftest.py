"""Shared test fixtures: an isolated in-memory DB and API client per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables on Base)
from app.db.base import Base


@pytest.fixture
def engine():
    """A fresh in-memory SQLite engine per test (StaticPool → one shared conn)."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session_factory(engine):
    return sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory):
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app

    def _override() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded_db(db):
    """Load the bundled demo dataset into the test DB."""
    from pathlib import Path

    from app.ingestion import csv_importer
    from app.ingestion.sources import CsvDataSource

    sample = Path(__file__).resolve().parent.parent / "data" / "sample"
    src = CsvDataSource(sample)
    csv_importer.import_wind_farms(db, src.wind_farms())
    csv_importer.import_customers(db, src.customers())
    csv_importer.import_contracts(db, src.contracts())
    csv_importer.import_generation(db, src.generation())
    csv_importer.import_consumption(db, src.consumption())
    return db
