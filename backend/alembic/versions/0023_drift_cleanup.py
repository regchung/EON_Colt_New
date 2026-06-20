"""消除既有 schema 漂移:對齊 model 與 DB(索引命名 + NOT NULL)

Revision ID: 0023
Revises: 0022

背景:多個既有表的欄位 model 宣告為 NOT NULL(且有 server_default),DB 卻為 nullable;
address_point 唯一索引名稱與 model 預設名不一致。補齊 models/__init__ 匯入後,
alembic check 暴露這些差異。本遷移將 DB 對齊 model,讓防漂移閘門恢復乾淨。
皆為既有欄位、含 server_default,先防禦性補值再設 NOT NULL,無資料風險。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, fallback SQL 值)— created_at 用 now(),類別欄用各自預設
_NOT_NULL = [
    ("driver_vehicle_assignment", "created_at", "now()"),
    ("fixed_route", "time_slot", "'全天'"),
    ("fixed_route", "match_field", "'any'"),
    ("fixed_route", "created_at", "now()"),
    ("pool_projection", "created_at", "now()"),
    ("unassigned_record", "created_at", "now()"),
]


def upgrade() -> None:
    # 1) address_point 唯一索引改回 model 預設名
    op.execute("ALTER INDEX IF EXISTS ix_address_point_std "
               "RENAME TO ix_address_point_standardized_address")
    # 2) 對齊 NOT NULL(先補可能的 NULL,再設約束)
    for table, col, fallback in _NOT_NULL:
        op.execute(f"UPDATE {table} SET {col} = {fallback} WHERE {col} IS NULL")
        op.alter_column(table, col, nullable=False)


def downgrade() -> None:
    for table, col, _ in _NOT_NULL:
        op.alter_column(table, col, nullable=True)
    op.execute("ALTER INDEX IF EXISTS ix_address_point_standardized_address "
               "RENAME TO ix_address_point_std")
