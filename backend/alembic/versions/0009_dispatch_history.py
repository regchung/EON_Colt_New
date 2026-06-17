"""orders.source_order_no + dispatch_history table

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("source_order_no", sa.String(length=40), nullable=True))
    op.create_index("ix_orders_source_order_no", "orders", ["source_order_no"])

    op.create_table(
        "dispatch_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_order_no", sa.String(length=40), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("pickup_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plate", sa.String(length=20), nullable=True),
        sa.Column("driver_name", sa.String(length=50), nullable=True),
        sa.Column("driver_phone", sa.String(length=30), nullable=True),
        sa.Column("dispatcher", sa.String(length=50), nullable=True),
        sa.Column("pickup_city", sa.String(length=20), nullable=True),
        sa.Column("pickup_town", sa.String(length=20), nullable=True),
        sa.Column("dropoff_city", sa.String(length=20), nullable=True),
        sa.Column("dropoff_town", sa.String(length=20), nullable=True),
        sa.Column("pickup_address", sa.String(length=500), nullable=True),
        sa.Column("dropoff_address", sa.String(length=500), nullable=True),
        sa.Column("pickup_lng", sa.Float(), nullable=True),
        sa.Column("pickup_lat", sa.Float(), nullable=True),
        sa.Column("dropoff_lng", sa.Float(), nullable=True),
        sa.Column("dropoff_lat", sa.Float(), nullable=True),
        sa.Column("vehicle_type_req", sa.String(length=40), nullable=True),
        sa.Column("pax", sa.Integer(), nullable=True),
        sa.Column("wheelchair_count", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("est_minutes", sa.Float(), nullable=True),
        sa.Column("service_minutes", sa.Float(), nullable=True),
        sa.Column("fare_negotiated", sa.Float(), nullable=True),
        sa.Column("subsidy", sa.Float(), nullable=True),
        sa.Column("self_pay", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=True),
        sa.Column("order_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("op_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dispatch_history_source_order_no", "dispatch_history", ["source_order_no"])
    op.create_index("ix_dispatch_history_service_date", "dispatch_history", ["service_date"])
    op.create_index("ix_dispatch_history_plate", "dispatch_history", ["plate"])


def downgrade() -> None:
    op.drop_table("dispatch_history")
    op.drop_index("ix_orders_source_order_no", table_name="orders")
    op.drop_column("orders", "source_order_no")
