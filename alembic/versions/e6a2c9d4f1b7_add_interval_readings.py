"""add interval_readings (15-minute interval data pipeline, B6)

Revision ID: e6a2c9d4f1b7
Revises: d5f0a1b2c384
Create Date: 2026-07-29 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6a2c9d4f1b7"
down_revision: str | None = "d5f0a1b2c384"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interval_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("energy_mwh", sa.Float(), nullable=False),
        sa.Column("data_source", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_interval_readings_kind", "interval_readings", ["kind"])
    op.create_index("ix_interval_readings_ref_id", "interval_readings", ["ref_id"])
    op.create_index("ix_interval_readings_ts", "interval_readings", ["ts"])
    op.create_index(
        "ix_interval_kind_ref_ts", "interval_readings", ["kind", "ref_id", "ts"]
    )


def downgrade() -> None:
    op.drop_index("ix_interval_kind_ref_ts", table_name="interval_readings")
    op.drop_index("ix_interval_readings_ts", table_name="interval_readings")
    op.drop_index("ix_interval_readings_ref_id", table_name="interval_readings")
    op.drop_index("ix_interval_readings_kind", table_name="interval_readings")
    op.drop_table("interval_readings")
