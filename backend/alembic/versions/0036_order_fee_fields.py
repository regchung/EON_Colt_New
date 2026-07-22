"""orders 新增費用欄位(里程/車資/陪同金額/自付金額/補助餘額)

Revision ID: 0036
Revises: 0035
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("mileage", sa.Float, nullable=True))
    op.add_column("orders", sa.Column("fare", sa.Integer, nullable=True))
    op.add_column("orders", sa.Column("companion_fee", sa.Integer, nullable=True))
    op.add_column("orders", sa.Column("self_pay_amount", sa.Integer, nullable=True))
    op.add_column("orders", sa.Column("subsidy_balance", sa.String(30), nullable=True))


def downgrade() -> None:
    for col in ["subsidy_balance", "self_pay_amount", "companion_fee", "fare", "mileage"]:
        op.drop_column("orders", col)
