"""orders 新增付款方式/性質/客戶所在地區

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("payment_type", sa.String(10), nullable=True))
    op.add_column("orders", sa.Column("order_nature", sa.String(50), nullable=True))
    op.add_column("orders", sa.Column("customer_region", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "customer_region")
    op.drop_column("orders", "order_nature")
    op.drop_column("orders", "payment_type")
