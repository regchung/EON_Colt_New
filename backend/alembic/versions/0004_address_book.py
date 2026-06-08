"""address book: address_point + address_alias (replaces geocode_cache)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("geocode_cache")

    op.create_table(
        "address_point",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("standardized_address", sa.String(length=500), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("precision", sa.String(length=10), nullable=True),
        sa.Column("city", sa.String(length=20), nullable=True),
        sa.Column("town", sa.String(length=20), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_address_point_std", "address_point", ["standardized_address"], unique=True)

    op.create_table(
        "address_alias",
        sa.Column("raw_address", sa.String(length=500), nullable=False),
        sa.Column("address_point_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["address_point_id"], ["address_point.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("raw_address"),
    )


def downgrade() -> None:
    op.drop_table("address_alias")
    op.drop_index("ix_address_point_std", table_name="address_point")
    op.drop_table("address_point")

    op.create_table(
        "geocode_cache",
        sa.Column("address", sa.String(length=500), nullable=False),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("precision", sa.String(length=10), nullable=True),
        sa.Column("matched_query", sa.String(length=500), nullable=True),
        sa.Column("found", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("address"),
    )
