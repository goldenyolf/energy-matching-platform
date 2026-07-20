"""add trec_batches

Revision ID: 7e04a6368520
Revises: 0f179db933d6
Create Date: 2026-07-20 23:53:23.894543
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e04a6368520'
down_revision: str | None = '0f179db933d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trec_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_no", sa.String(length=120), nullable=False),
        sa.Column("wind_farm_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("quantity_mwh", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["wind_farm_id"], ["wind_farms.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trec_batches_batch_no"), "trec_batches", ["batch_no"], unique=True
    )
    op.create_index(
        op.f("ix_trec_batches_wind_farm_id"), "trec_batches", ["wind_farm_id"]
    )
    op.create_index(
        op.f("ix_trec_batches_customer_id"), "trec_batches", ["customer_id"]
    )
    op.create_index(op.f("ix_trec_batches_period"), "trec_batches", ["period"])


def downgrade() -> None:
    op.drop_index(op.f("ix_trec_batches_period"), table_name="trec_batches")
    op.drop_index(op.f("ix_trec_batches_customer_id"), table_name="trec_batches")
    op.drop_index(op.f("ix_trec_batches_wind_farm_id"), table_name="trec_batches")
    op.drop_index(op.f("ix_trec_batches_batch_no"), table_name="trec_batches")
    op.drop_table("trec_batches")
