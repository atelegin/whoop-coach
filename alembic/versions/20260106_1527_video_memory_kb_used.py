"""video_memory_kb_used

Revision ID: a1b2c3d4e5f6
Revises: 33660aa2d477
Create Date: 2026-01-06 15:27:00.000000+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '33660aa2d477'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Videos: add usage tracking columns
    op.add_column('videos', sa.Column(
        'usage_count', sa.Integer(), nullable=False, server_default=sa.text('1')
    ))
    op.add_column('videos', sa.Column(
        'first_seen_at', sa.DateTime(timezone=True), nullable=False,
        server_default=sa.text('(CURRENT_TIMESTAMP)')
    ))
    op.add_column('videos', sa.Column(
        'last_used_at', sa.DateTime(timezone=True), nullable=False,
        server_default=sa.text('(CURRENT_TIMESTAMP)')
    ))
    
    # PendingLogs: add kb_used prompt state columns
    op.add_column('pending_logs', sa.Column(
        'kb_used_prompt_sent_at', sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column('pending_logs', sa.Column(
        'kb_used_answered_at', sa.DateTime(timezone=True), nullable=True
    ))


def downgrade() -> None:
    # PendingLogs
    op.drop_column('pending_logs', 'kb_used_answered_at')
    op.drop_column('pending_logs', 'kb_used_prompt_sent_at')
    
    # Videos
    op.drop_column('videos', 'last_used_at')
    op.drop_column('videos', 'first_seen_at')
    op.drop_column('videos', 'usage_count')
