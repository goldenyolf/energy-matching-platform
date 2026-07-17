"""add time_slot to gen/consumption

Revision ID: 2440c428ccf6
Revises: fa6b9882de2c
Create Date: 2026-07-17 12:48:10.488267
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "2440c428ccf6"
down_revision: str | None = "fa6b9882de2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    timeslot = sa.Enum("PEAK", "HALF_PEAK", "OFF_PEAK", name="timeslot")
    timeslot.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("generation_data", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "time_slot",
                sa.Enum(
                    "PEAK", "HALF_PEAK", "OFF_PEAK", name="timeslot", create_type=False
                ),
                nullable=True,
            )
        )
    with op.batch_alter_table("consumption_data", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "time_slot",
                sa.Enum(
                    "PEAK", "HALF_PEAK", "OFF_PEAK", name="timeslot", create_type=False
                ),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("consumption_data", schema=None) as batch_op:
        batch_op.drop_column("time_slot")
    with op.batch_alter_table("generation_data", schema=None) as batch_op:
        batch_op.drop_column("time_slot")
    sa.Enum(name="timeslot").drop(op.get_bind(), checkfirst=True)
