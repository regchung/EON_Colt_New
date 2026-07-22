"""vehicles 新增指定服務地區欄位

Revision ID: 0035
Revises: 0034
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("district", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "district")
