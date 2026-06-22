"""vehicles 新增 wheelchair(可載輪椅數)欄位

Revision ID: 0025
Revises: 0024

由車隊名冊「輪椅數」回填;含 server_default='0',既有列補 0,無資料風險。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column(
        "wheelchair", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("vehicles", "wheelchair")
