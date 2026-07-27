"""drop customer tax_id / contact / transfer_price

Revision ID: a2f7c3e91b48
Revises: 9a1e4b2c8d70
Create Date: 2026-07-28 05:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2f7c3e91b48"
down_revision: str | None = "9a1e4b2c8d70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (name, type-for-downgrade)
_DROP = [
    ("tax_id", sa.String(length=20)),
    ("contact_name", sa.String(length=100)),
    ("contact_email", sa.String(length=200)),
    ("transfer_price_per_kwh", sa.Float()),
]


def upgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, _ in _DROP:
            batch_op.drop_column(name)


def downgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, col_type in reversed(_DROP):
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
