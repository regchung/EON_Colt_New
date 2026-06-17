"""fleet marker: orders.fleet, dispatch_history.fleet, vehicles/drivers.home_fleet

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("fleet", sa.String(length=20), nullable=True))
    op.create_index("ix_orders_fleet", "orders", ["fleet"])
    op.add_column("dispatch_history", sa.Column("fleet", sa.String(length=20), nullable=True))
    op.create_index("ix_dispatch_history_fleet", "dispatch_history", ["fleet"])
    op.add_column("vehicles", sa.Column("home_fleet", sa.String(length=20), nullable=True))
    op.add_column("drivers", sa.Column("home_fleet", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("drivers", "home_fleet")
    op.drop_column("vehicles", "home_fleet")
    op.drop_index("ix_dispatch_history_fleet", table_name="dispatch_history")
    op.drop_column("dispatch_history", "fleet")
    op.drop_index("ix_orders_fleet", table_name="orders")
    op.drop_column("orders", "fleet")
