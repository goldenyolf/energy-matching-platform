"""drop customer agent / address / phone

Revision ID: b3d8e5f0a291
Revises: a2f7c3e91b48
Create Date: 2026-07-28 06:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d8e5f0a291"
down_revision: str | None = "a2f7c3e91b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = [
    ("agent", sa.String(length=100)),
    ("address", sa.String(length=300)),
    ("phone", sa.String(length=50)),
]


def upgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, _ in _DROP:
            batch_op.drop_column(name)


def downgrade() -> None:
    with op.batch_alter_table("customers", schema=None) as batch_op:
        for name, col_type in reversed(_DROP):
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
