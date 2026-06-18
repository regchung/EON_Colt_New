"""訂單個案/地標標籤:orders.case_tag(供固定行程匹配)

Revision ID: 0020
Revises: 0019
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("case_tag", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "case_tag")
