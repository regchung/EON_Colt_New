"""route_stop table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "route_stop",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_route_stop_service_date", "route_stop", ["service_date"])
    op.create_index("ix_route_stop_vehicle_id", "route_stop", ["vehicle_id"])


def downgrade() -> None:
    op.drop_index("ix_route_stop_vehicle_id", table_name="route_stop")
    op.drop_index("ix_route_stop_service_date", table_name="route_stop")
    op.drop_table("route_stop")
