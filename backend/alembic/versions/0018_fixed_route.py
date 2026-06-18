"""固定行程指定司機:fixed_route

Revision ID: 0018
Revises: 0017
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fixed_route",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("keyword", sa.String(length=60), index=True, nullable=False),
        sa.Column("driver_name", sa.String(length=50), nullable=False),
        sa.Column("time_slot", sa.String(length=20), server_default="全天"),
        sa.Column("match_field", sa.String(length=20), server_default="any"),
        sa.Column("fleet", sa.String(length=20), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fixed_route")
