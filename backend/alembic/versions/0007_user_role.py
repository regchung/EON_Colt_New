"""add role to users

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.String(length=20), nullable=False, server_default="admin"))
    # 既有帳號全部設為 admin，新建司機帳號才設 driver
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'admin'")


def downgrade() -> None:
    op.drop_column("users", "role")
