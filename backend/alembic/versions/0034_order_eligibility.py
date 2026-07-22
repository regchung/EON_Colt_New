"""orders 新增身份資格欄位

Revision ID: 0034
Revises: 0033
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("eligibility", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "eligibility")
