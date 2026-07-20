"""add meters

Revision ID: 0f179db933d6
Revises: 2440c428ccf6
Create Date: 2026-07-20 17:28:40.833319
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f179db933d6'
down_revision: str | None = '2440c428ccf6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=True),
        sa.Column("re_target_percent", sa.Float(), nullable=False),
        sa.Column("annual_consumption_mwh", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_meters_code"), "meters", ["code"], unique=True)
    op.create_index(op.f("ix_meters_customer_id"), "meters", ["customer_id"])
    with op.batch_alter_table("consumption_data") as batch:
        batch.add_column(sa.Column("meter_id", sa.Integer(), nullable=True))
        batch.create_index(op.f("ix_consumption_data_meter_id"), ["meter_id"])
        batch.create_foreign_key(
            "fk_consumption_meter", "meters", ["meter_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("consumption_data") as batch:
        batch.drop_constraint("fk_consumption_meter", type_="foreignkey")
        batch.drop_index(op.f("ix_consumption_data_meter_id"))
        batch.drop_column("meter_id")
    op.drop_index(op.f("ix_meters_customer_id"), table_name="meters")
    op.drop_index(op.f("ix_meters_code"), table_name="meters")
    op.drop_table("meters")
