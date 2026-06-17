"""orders pool consent audit (共乘同意留痕)

Revision ID: 0013
Revises: 0012
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("pool_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("pool_consent_by", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "pool_consent_by")
    op.drop_column("orders", "pool_consent_at")
