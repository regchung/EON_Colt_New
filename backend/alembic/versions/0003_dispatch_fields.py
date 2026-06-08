"""orders: add dispatch_seq, eta

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("dispatch_seq", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("eta", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "eta")
    op.drop_column("orders", "dispatch_seq")
