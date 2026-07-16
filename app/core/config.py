"""Application configuration via environment variables (12-factor)."""

from __future__ import annotations

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


settings = Settings()
