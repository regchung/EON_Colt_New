"""dispatch_history.pool_consent:人工派遣單的共乘同意欄(補齊)

Revision ID: 0031
Revises: 0030

人工派遣資料表原無共乘同意欄。新增可空 bool:None=未知/未擷取、True=同意、False=不同意。
來源檔若有共乘訊號(共乘組別/是否願意共乘)由匯入回填;無則留 None。不動既有資料。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("dispatch_history", sa.Column("pool_consent", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("dispatch_history", "pool_consent")
