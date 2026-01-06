"""Add WHOOP snapshot columns to pending_logs.

Revision ID: 20260106_1606_whoop_snapshot
Revises: a1b2c3d4e5f6
Create Date: 2026-01-06 16:06:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260106_1606_whoop_snapshot'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('pending_logs', sa.Column('whoop_workout_id', sa.String(64), nullable=True))
    op.add_column('pending_logs', sa.Column('whoop_workout_type', sa.String(64), nullable=True))
    op.add_column('pending_logs', sa.Column('whoop_duration_s', sa.Integer(), nullable=True))
    op.add_column('pending_logs', sa.Column('whoop_strain', sa.Float(), nullable=True))
    op.add_column('pending_logs', sa.Column('whoop_hr_avg', sa.Integer(), nullable=True))
    op.add_column('pending_logs', sa.Column('whoop_hr_max', sa.Integer(), nullable=True))
    op.add_column('pending_logs', sa.Column('matched_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('pending_logs', 'matched_at')
    op.drop_column('pending_logs', 'whoop_hr_max')
    op.drop_column('pending_logs', 'whoop_hr_avg')
    op.drop_column('pending_logs', 'whoop_strain')
    op.drop_column('pending_logs', 'whoop_duration_s')
    op.drop_column('pending_logs', 'whoop_workout_type')
    op.drop_column('pending_logs', 'whoop_workout_id')
