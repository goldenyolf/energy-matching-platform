"""customer company info + per-meter load data

Revision ID: 9a1e4b2c8d70
Revises: 8f3a1c7d9e21
Create Date: 2026-07-28 04:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a1e4b2c8d70"
down_revision: str | None = "8f3a1c7d9e21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# customer: drop the misplaced capacity/tariff/price columns, add company info
_CUST_DROP = [
    ("contracted_capacity_kw", sa.Float()),
    ("tariff_type", sa.String(length=30)),
    ("peak_price_per_kwh", sa.Float()),
    ("half_peak_price_per_kwh", sa.Float()),
    ("off_peak_price_per_kwh", sa.Float()),
]
_CUST_ADD = [
    ("agent", sa.String(length=100)),
    ("address", sa.String(length=300)),
    ("phone", sa.String(length=50)),
    ("tax_id", sa.String(length=20)),
    ("contact_name", sa.String(length=100)),
    ("contact_email", sa.String(length=200)),
]
# meter: per-電號 load data
_METER_ADD = [
    ("usage_name", sa.String(length=200)),
    ("contracted_capacity_kw", sa.Float()),
    ("tariff_type", sa.String(length=40)),
    ("load_data_type", sa.String(length=100)),
    ("peak_kwh", sa.Float()),
    ("half_peak_kwh", sa.Float()),
    ("saturday_half_peak_kwh", sa.Float()),
    ("off_peak_kwh", sa.Float()),
    ("total_kwh", sa.Float()),
    ("data_period", sa.String(length=40)),
]


def upgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, col_type in _CUST_ADD:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
        for name, _ in _CUST_DROP:
            batch_op.drop_column(name)
    with op.batch_alter_table("meters", schema=None) as batch_op:
        for name, col_type in _METER_ADD:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("meters", schema=None) as batch_op:
        for name, _ in reversed(_METER_ADD):
            batch_op.drop_column(name)
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, col_type in reversed(_CUST_DROP):
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
        for name, _ in reversed(_CUST_ADD):
            batch_op.drop_column(name)
