"""班表:shift_pattern + shift_exception

Revision ID: 0016
Revises: 0015
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_pattern",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_id", sa.Integer(),
                  sa.ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("shift_start", sa.Time(), nullable=True),
        sa.Column("shift_end", sa.Time(), nullable=True),
        sa.UniqueConstraint("vehicle_id", "weekday", name="uq_shift_pattern_veh_wd"),
    )
    op.create_table(
        "shift_exception",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_id", sa.Integer(),
                  sa.ForeignKey("vehicles.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("ex_date", sa.Date(), index=True, nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shift_start", sa.Time(), nullable=True),
        sa.Column("shift_end", sa.Time(), nullable=True),
        sa.Column("reason", sa.String(length=50), nullable=True),
        sa.UniqueConstraint("vehicle_id", "ex_date", name="uq_shift_exc_veh_date"),
    )


def downgrade() -> None:
    op.drop_table("shift_exception")
    op.drop_table("shift_pattern")
