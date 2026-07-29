"""add batteries (customer-side storage, A8)

Revision ID: f7b3c8d5e2a9
Revises: e6a2c9d4f1b7
Create Date: 2026-07-29 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7b3c8d5e2a9"
down_revision: str | None = "e6a2c9d4f1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "batteries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("energy_capacity_mwh", sa.Float(), nullable=False),
        sa.Column("power_mw", sa.Float(), nullable=False),
        sa.Column("round_trip_efficiency_percent", sa.Float(), nullable=False),
        sa.Column("initial_soc_percent", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_batteries_code", "batteries", ["code"], unique=True)
    op.create_index("ix_batteries_customer_id", "batteries", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_batteries_customer_id", table_name="batteries")
    op.drop_index("ix_batteries_code", table_name="batteries")
    op.drop_table("batteries")
