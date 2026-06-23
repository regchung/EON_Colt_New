"""orders.occupancy_min:固定趟整趟佔用時間(分),既定區塊標記

Revision ID: 0027
Revises: 0026

新增可空欄位 orders.occupancy_min。None=一般單(原行為);設值=既定區塊。
不動既有資料,無風險。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("occupancy_min", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "occupancy_min")
