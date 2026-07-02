"""auto_dispatch_stop:自動派遣停靠明細(對比 dry-run 每車每停靠點)

Revision ID: 0030
Revises: 0029

新增表存放對比引擎自動派遣的每車每停靠點(近似 route_stop + occupancy/is_support),
由 comparison.persist_day 每次跑對比時清/重寫該日。不動既有資料。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auto_dispatch_stop",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("fleet", sa.String(length=20), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("plate", sa.String(length=20), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occupancy", sa.Integer(), nullable=True),
        sa.Column("is_support", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("window_min", sa.Integer(), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auto_dispatch_stop_service_date", "auto_dispatch_stop", ["service_date"])
    op.create_index("ix_auto_dispatch_stop_fleet", "auto_dispatch_stop", ["fleet"])
    op.create_index("ix_auto_dispatch_stop_vehicle_id", "auto_dispatch_stop", ["vehicle_id"])


def downgrade() -> None:
    op.drop_index("ix_auto_dispatch_stop_vehicle_id", table_name="auto_dispatch_stop")
    op.drop_index("ix_auto_dispatch_stop_fleet", table_name="auto_dispatch_stop")
    op.drop_index("ix_auto_dispatch_stop_service_date", table_name="auto_dispatch_stop")
    op.drop_table("auto_dispatch_stop")
