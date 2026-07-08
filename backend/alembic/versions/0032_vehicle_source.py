"""vehicle.vehicle_source: 車輛來源欄位(獎助/特約)

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa

revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS vehicle_source VARCHAR(10)")


def downgrade():
    op.drop_column('vehicles', 'vehicle_source')
