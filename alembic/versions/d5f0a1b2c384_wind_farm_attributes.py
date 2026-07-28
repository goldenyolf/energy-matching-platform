"""wind farm attributes: type, capacity factor (P50/P90), turbines, voltage

Revision ID: d5f0a1b2c384
Revises: c4e9f1a2b673
Create Date: 2026-07-28 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f0a1b2c384"
down_revision: str | None = "c4e9f1a2b673"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADD = [
    ("farm_type", sa.String(length=20)),
    ("capacity_factor_percent", sa.Float()),
    ("p90_capacity_factor_percent", sa.Float()),
    ("turbine_count", sa.Integer()),
    ("grid_connection_voltage", sa.String(length=40)),
]


def upgrade() -> None:
    with op.batch_alter_table("wind_farms", schema=None) as batch_op:
        for name, col_type in _ADD:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("wind_farms", schema=None) as batch_op:
        for name, _ in reversed(_ADD):
            batch_op.drop_column(name)
