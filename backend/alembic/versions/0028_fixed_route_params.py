"""fixed_route 既定區塊維護欄位:起迄/車牌/起始時段/佔用時間/乘客數/車型/輪椅/可併

Revision ID: 0028
Revises: 0027

為固定行程補上「該有的參數欄位」供維護;既有 22 列以預設值回填,無風險。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fixed_route", sa.Column("pickup_address", sa.Text(), nullable=True))
    op.add_column("fixed_route", sa.Column("dropoff_address", sa.Text(), nullable=True))
    op.add_column("fixed_route", sa.Column("plate", sa.String(length=20), nullable=True))
    op.add_column("fixed_route", sa.Column("start_time", sa.String(length=5), nullable=True))
    op.add_column("fixed_route", sa.Column("occupancy_min", sa.Integer(), nullable=True))
    op.add_column("fixed_route", sa.Column("pax", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("fixed_route", sa.Column("vehicle_type", sa.String(length=10), nullable=False, server_default="normal"))
    op.add_column("fixed_route", sa.Column("wheelchair", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("fixed_route", sa.Column("allow_pool", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for col in ("allow_pool", "wheelchair", "vehicle_type", "pax", "occupancy_min",
                "start_time", "plate", "dropoff_address", "pickup_address"):
        op.drop_column("fixed_route", col)
