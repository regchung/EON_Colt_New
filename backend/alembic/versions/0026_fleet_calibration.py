"""fleet_calibration:每車行(區域)每趟作業時間 + 速度係數(歷史校準)

Revision ID: 0026
Revises: 0025

新表 fleet_calibration。不動既有資料,無風險。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fleet_calibration",
        sa.Column("fleet", sa.String(length=30), primary_key=True),
        sa.Column("service_normal_sec", sa.Integer(), nullable=False, server_default="2400"),
        sa.Column("service_welfare_sec", sa.Integer(), nullable=False, server_default="2400"),
        sa.Column("speed_factor", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("fleet_calibration")
