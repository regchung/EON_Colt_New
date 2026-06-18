"""未派訂單記錄:unassigned_record

Revision ID: 0017
Revises: 0016
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unassigned_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("service_date", sa.Date(), index=True, nullable=False),
        sa.Column("fleet", sa.String(length=20), index=True, nullable=True),
        sa.Column("order_id", sa.Integer(),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), index=True, nullable=True),
        sa.Column("source_order_no", sa.String(length=40), nullable=True),
        sa.Column("reason_code", sa.String(length=20), nullable=False),
        sa.Column("reason_detail", sa.String(length=200), nullable=True),
        sa.Column("window_min", sa.Integer(), nullable=True),
        sa.Column("human_plate", sa.String(length=20), nullable=True),
        sa.Column("human_driver", sa.String(length=50), nullable=True),
        sa.Column("feedback_category", sa.String(length=30), nullable=True),
        sa.Column("feedback_note", sa.String(length=500), nullable=True),
        sa.Column("feedback_by", sa.String(length=50), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("unassigned_record")
