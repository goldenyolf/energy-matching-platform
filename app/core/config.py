"""Application configuration via environment variables (12-factor)."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, overridable through environment or a .env file.

    ``DATABASE_URL`` defaults to a local SQLite file so the app runs with zero
    external services. Docker Compose overrides it to PostgreSQL.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Energy Matching Platform"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"

    # SQLite by default → no external DB needed for local dev / tests.
    # Postgres example: postgresql+psycopg://user:pass@db:5432/energy_matching
    database_url: str = "sqlite:///./energy_matching.db"

    # Streamlit dashboard → backend base URL
    api_base_url: str = "http://localhost:8000"

    # Economics (P2 evaluation) — NTD/kWh
    grey_price_per_kwh: float = 3.0
    default_feed_in_price_per_kwh: float = 4.0

    # Economic optimizer (P3) — structural constraints, off by default
    optimize_min_sites_per_customer: int = 0
    optimize_min_site_allocation_percent: float = 0.0

    # Investment analysis (ROI / payback) — illustrative demo defaults
    capex_per_mw: float = 80_000_000.0  # NTD per MW installed
    om_rate_percent: float = 2.0  # annual O&M as % of CAPEX

    # Transfer settlement (P5) — illustrative demo defaults
    wheeling_fee_per_kwh: float = 0.1  # NTD/kWh Taipower 轉供/輸配 service fee
    grid_emission_factor_kg_per_kwh: float = 0.494  # Taiwan 2023 grid factor

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3_driver(cls, v: str) -> str:
        """Force psycopg v3 for Postgres.

        A bare ``postgresql://`` / ``postgres://`` (what Neon and Render hand you
        when you copy a connection string) makes SQLAlchemy default to psycopg2,
        which is not installed — this project uses ``psycopg[binary]`` (v3).
        Normalizing here means a plain copy-pasted URL just works.
        """
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://") :]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://") :]
        return v


settings = Settings()
