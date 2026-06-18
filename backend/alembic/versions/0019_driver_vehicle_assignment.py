"""當日駕駛-車輛指派:driver_vehicle_assignment

Revision ID: 0019
Revises: 0018
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "driver_vehicle_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_date", sa.Date(), index=True, nullable=False),
        sa.Column("driver_id", sa.Integer(),
                  sa.ForeignKey("drivers.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("vehicle_id", sa.Integer(),
                  sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("service_date", "driver_id", name="uq_dva_date_driver"),
    )


def downgrade() -> None:
    op.drop_table("driver_vehicle_assignment")
