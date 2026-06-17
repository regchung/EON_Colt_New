"""dispatch_comparison table

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispatch_comparison",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fleet", sa.String(length=20), nullable=True),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("window_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("n_orders", sa.Integer(), nullable=False),
        sa.Column("human_vehicles", sa.Integer(), nullable=False),
        sa.Column("vroom_vehicles", sa.Integer(), nullable=False),
        sa.Column("vroom_unassigned", sa.Integer(), nullable=False),
        sa.Column("saved_vehicles", sa.Integer(), nullable=False),
        sa.Column("human_distance_m", sa.Float(), nullable=True),
        sa.Column("human_minutes", sa.Float(), nullable=True),
        sa.Column("vroom_drive_sec", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dispatch_comparison_fleet", "dispatch_comparison", ["fleet"])
    op.create_index("ix_dispatch_comparison_service_date", "dispatch_comparison", ["service_date"])


def downgrade() -> None:
    op.drop_table("dispatch_comparison")
