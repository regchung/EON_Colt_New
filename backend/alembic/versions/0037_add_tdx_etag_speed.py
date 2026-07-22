"""add tdx_etag_speed table

Revision ID: 0037
Revises: 78f39fba5c81
Create Date: 2026-07-21
"""
from alembic import op
import sqlalchemy as sa

revision = '0037'
down_revision = '78f39fba5c81'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'tdx_etag_speed',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('etag_pair_id', sa.String(50), nullable=False),
        sa.Column('collected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('space_mean_speed', sa.Float(), nullable=True),
        sa.Column('travel_time', sa.Integer(), nullable=True),
        sa.Column('vehicle_count', sa.Integer(), nullable=True),
        sa.Column('vehicle_type', sa.Integer(), nullable=True),
    )
    op.create_index('ix_etag_speed_pair_time', 'tdx_etag_speed', ['etag_pair_id', 'collected_at'])
    op.create_index('ix_etag_speed_collected_at', 'tdx_etag_speed', ['collected_at'])


def downgrade() -> None:
    op.drop_index('ix_etag_speed_collected_at')
    op.drop_index('ix_etag_speed_pair_time')
    op.drop_table('tdx_etag_speed')
