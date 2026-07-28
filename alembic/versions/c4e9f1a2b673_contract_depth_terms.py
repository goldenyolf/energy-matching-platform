"""contract depth: monthly shares, take-or-pay, price escalation

Revision ID: c4e9f1a2b673
Revises: b3d8e5f0a291
Create Date: 2026-07-28 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e9f1a2b673"
down_revision: str | None = "b3d8e5f0a291"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ADD = [
    ("monthly_shares", sa.JSON()),
    ("min_offtake_percent", sa.Float()),
    ("price_escalation_percent", sa.Float()),
    ("price_base_year", sa.Integer()),
]


def upgrade() -> None:
    with op.batch_alter_table("contracts", schema=None) as batch_op:
        for name, col_type in _ADD:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contracts", schema=None) as batch_op:
        for name, _ in reversed(_ADD):
            batch_op.drop_column(name)
