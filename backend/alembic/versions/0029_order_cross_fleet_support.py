"""orders.support_fleet / dispatch_note:跨車行支援留痕

Revision ID: 0029
Revises: 0028

自動派遣「本車行優先→運能不足由他隊支援」時,於訂單記錄:
- support_fleet:實際出車車輛所屬車行(當 ≠ 訂單車行時填);None=本車行自派/未派。
- dispatch_note :支援原因白話。
皆可空,不動既有資料,無風險。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("support_fleet", sa.String(length=20), nullable=True))
    op.add_column("orders", sa.Column("dispatch_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "dispatch_note")
    op.drop_column("orders", "support_fleet")
