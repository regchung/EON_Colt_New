"""drivers / vehicles 新增 suspended(停派)欄位

Revision ID: 0024
Revises: 0023

停派旗標:標記後不納入自動派遣;與 active(是否在籍)分離。
含 server_default='false',既有列自動補 False(啟用),無資料風險。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("drivers", "vehicles"):
        op.add_column(table, sa.Column(
            "suspended", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for table in ("drivers", "vehicles"):
        op.drop_column(table, "suspended")
