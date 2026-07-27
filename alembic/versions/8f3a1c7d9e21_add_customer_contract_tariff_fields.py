"""add customer contract/tariff fields

Revision ID: 8f3a1c7d9e21
Revises: 7e04a6368520
Create Date: 2026-07-28 03:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f3a1c7d9e21"
down_revision: str | None = "7e04a6368520"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    ("contracted_capacity_kw", sa.Float()),
    ("transfer_price_per_kwh", sa.Float()),
    ("tariff_type", sa.String(length=30)),
    ("peak_price_per_kwh", sa.Float()),
    ("half_peak_price_per_kwh", sa.Float()),
    ("off_peak_price_per_kwh", sa.Float()),
]


def upgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, col_type in _COLUMNS:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, _ in reversed(_COLUMNS):
            batch_op.drop_column(name)
