"""DATABASE_URL is normalized to the installed psycopg v3 driver.

A bare ``postgresql://`` (what Neon/Render hand you when you copy a connection
string) makes SQLAlchemy default to psycopg2, which is NOT installed — the app
uses psycopg v3. Normalizing the scheme keeps deploys from crashing at boot.
"""

from app.core.config import Settings


def test_bare_postgresql_scheme_gets_psycopg3_driver():
    s = Settings(database_url="postgresql://u:p@host/db?sslmode=require")
    assert s.database_url == "postgresql+psycopg://u:p@host/db?sslmode=require"


def test_postgres_short_scheme_normalized():
    s = Settings(database_url="postgres://u:p@host/db")
    assert s.database_url == "postgresql+psycopg://u:p@host/db"


def test_explicit_psycopg_scheme_left_unchanged():
    url = "postgresql+psycopg://u:p@host/db"
    assert Settings(database_url=url).database_url == url


def test_sqlite_left_unchanged():
    url = "sqlite:///./energy_matching.db"
    assert Settings(database_url=url).database_url == url
