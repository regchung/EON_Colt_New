"""固定行程新增指定姓名比對:fixed_route.match_name

Revision ID: 0021
Revises: 0020
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fixed_route", sa.Column("match_name", sa.String(length=50), nullable=True))
    # keyword 改可空(允許「只靠姓名比對」的規則)
    op.alter_column("fixed_route", "keyword", existing_type=sa.String(length=60), nullable=True)


def downgrade() -> None:
    op.alter_column("fixed_route", "keyword", existing_type=sa.String(length=60), nullable=False)
    op.drop_column("fixed_route", "match_name")
