"""roster_driver_id_remove_driver_vehicle_id

Revision ID: 1cad90fa54e3
Revises: 0037
Create Date: 2026-07-10 18:50:40.949616

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = '1cad90fa54e3'
down_revision: Union[str, None] = '0037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    # drop drivers.vehicle_id (若存在)
    fks = [fk['name'] for fk in inspector.get_foreign_keys('drivers')]
    if 'drivers_vehicle_id_fkey' in fks:
        op.drop_constraint('drivers_vehicle_id_fkey', 'drivers', type_='foreignkey')
    cols = [c['name'] for c in inspector.get_columns('drivers')]
    if 'vehicle_id' in cols:
        op.drop_column('drivers', 'vehicle_id')

    # add shift_exception.driver_id (若不存在)
    exc_cols = [c['name'] for c in inspector.get_columns('shift_exception')]
    if 'driver_id' not in exc_cols:
        op.add_column('shift_exception', sa.Column('driver_id', sa.Integer(), nullable=True))
        op.create_index(op.f('ix_shift_exception_driver_id'), 'shift_exception', ['driver_id'], unique=False)
        op.create_foreign_key(None, 'shift_exception', 'drivers', ['driver_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    exc_cols = [c['name'] for c in inspector.get_columns('shift_exception')]
    if 'driver_id' in exc_cols:
        op.drop_constraint(None, 'shift_exception', type_='foreignkey')
        op.drop_index(op.f('ix_shift_exception_driver_id'), table_name='shift_exception')
        op.drop_column('shift_exception', 'driver_id')

    cols = [c['name'] for c in inspector.get_columns('drivers')]
    if 'vehicle_id' not in cols:
        op.add_column('drivers', sa.Column('vehicle_id', sa.INTEGER(), autoincrement=False, nullable=True))
        op.create_foreign_key('drivers_vehicle_id_fkey', 'drivers', 'vehicles', ['vehicle_id'], ['id'], ondelete='SET NULL')
