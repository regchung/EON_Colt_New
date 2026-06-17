"""pool_projection 共乘增益投影彙總表

Revision ID: 0014
Revises: 0013
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pool_projection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fleet", sa.String(length=20), nullable=True, index=True),
        sa.Column("window_min", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("v_now", sa.Integer(), nullable=False),
        sa.Column("v_pool", sa.Integer(), nullable=False),
        sa.Column("saved_vehicles", sa.Integer(), nullable=False),
        sa.Column("ask_groups", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("pool_projection")
