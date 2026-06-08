"""initial schema: vehicles, drivers, orders

Revision ID: 0001
Revises:
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plate", sa.String(length=20), nullable=True),
        sa.Column("type", sa.String(length=10), nullable=False, server_default="normal"),
        sa.Column("seats", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("shift_start", sa.Time(), nullable=True),
        sa.Column("shift_end", sa.Time(), nullable=True),
        sa.Column("depot_lng", sa.Float(), nullable=True),
        sa.Column("depot_lat", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "drivers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("license_no", sa.String(length=30), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pickup_window_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("passenger_name", sa.String(length=50), nullable=True),
        sa.Column("passenger_phone", sa.String(length=30), nullable=True),
        sa.Column("pickup_address", sa.Text(), nullable=False),
        sa.Column("pickup_lng", sa.Float(), nullable=True),
        sa.Column("pickup_lat", sa.Float(), nullable=True),
        sa.Column("dropoff_address", sa.Text(), nullable=False),
        sa.Column("dropoff_lng", sa.Float(), nullable=True),
        sa.Column("dropoff_lat", sa.Float(), nullable=True),
        sa.Column("pax", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("vehicle_type", sa.String(length=10), nullable=False, server_default="normal"),
        sa.Column("need_wheelchair", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("allow_pool", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="imported"),
        sa.Column("assigned_vehicle_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_service_date", "orders", ["service_date"])
    op.create_index("ix_orders_status", "orders", ["status"])


def downgrade() -> None:
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_service_date", table_name="orders")
    op.drop_table("orders")
    op.drop_table("drivers")
    op.drop_table("vehicles")
