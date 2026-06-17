"""vehicle start/end depot coords (出車起點 / 收車終點)

Revision ID: 0012
Revises: 0011
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("start_lng", sa.Float(), nullable=True))
    op.add_column("vehicles", sa.Column("start_lat", sa.Float(), nullable=True))
    op.add_column("vehicles", sa.Column("end_lng", sa.Float(), nullable=True))
    op.add_column("vehicles", sa.Column("end_lat", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("vehicles", "end_lat")
    op.drop_column("vehicles", "end_lng")
    op.drop_column("vehicles", "start_lat")
    op.drop_column("vehicles", "start_lng")
