"""add_webhook_events_and_daily_plans

Revision ID: 8a43d7a965ec
Revises: cb0acf7393e4
Create Date: 2026-01-05 19:16:58.678620+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8a43d7a965ec'
down_revision: Union[str, None] = 'cb0acf7393e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create whoop_webhook_events table
    op.create_table(
        'whoop_webhook_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('trace_id', sa.String(64), nullable=False),
        sa.Column('sleep_id', sa.String(64), nullable=False),
        sa.Column('event_type', sa.String(32), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('trace_id'),
    )
    op.create_index('ix_webhook_events_sleep_id', 'whoop_webhook_events', ['sleep_id'])
    op.create_index('ix_webhook_events_user_status', 'whoop_webhook_events', ['user_id', 'status'])

    # Create daily_plans table
    op.create_table(
        'daily_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('plan_date', sa.Date(), nullable=False),
        sa.Column('sleep_id', sa.String(64), nullable=True),
        sa.Column('cycle_id', sa.Integer(), nullable=True),
        sa.Column('recovery_score', sa.Integer(), nullable=True),
        sa.Column('timezone_offset', sa.String(8), nullable=True),
        sa.Column('options_shown', sa.JSON(), nullable=True),
        sa.Column('scoring_debug', sa.JSON(), nullable=True),
        sa.Column('selected_option_id', sa.String(64), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('plan_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'plan_date', name='uq_daily_plan_user_date'),
    )
    op.create_index('ix_daily_plans_user_date', 'daily_plans', ['user_id', 'plan_date'])


def downgrade() -> None:
    op.drop_index('ix_daily_plans_user_date', table_name='daily_plans')
    op.drop_table('daily_plans')
    op.drop_index('ix_webhook_events_user_status', table_name='whoop_webhook_events')
    op.drop_index('ix_webhook_events_sleep_id', table_name='whoop_webhook_events')
    op.drop_table('whoop_webhook_events')
