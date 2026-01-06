"""add_kb_capabilities

Revision ID: 33660aa2d477
Revises: 8a43d7a965ec
Create Date: 2026-01-06 13:58:24.305831+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '33660aa2d477'
down_revision: Union[str, None] = '8a43d7a965ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users KB capability columns
    op.add_column('users', sa.Column('kb_overhead_max_kg', sa.Integer(), nullable=False, server_default=sa.text('12')))
    op.add_column('users', sa.Column('kb_heavy_kg', sa.Integer(), nullable=False, server_default=sa.text('20')))
    op.add_column('users', sa.Column('kb_swing_kg', sa.Integer(), nullable=False, server_default=sa.text('12')))
    
    # CHECK constraints for users (skip on SQLite - doesn't support ALTER TABLE ADD CONSTRAINT)
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.create_check_constraint('ck_users_kb_overhead_max_kg', 'users', 'kb_overhead_max_kg IN (12)')
        op.create_check_constraint('ck_users_kb_heavy_kg', 'users', 'kb_heavy_kg IN (12, 20)')
        op.create_check_constraint('ck_users_kb_swing_kg', 'users', 'kb_swing_kg IN (12, 20)')
    
    # Videos movement_tags
    op.add_column('videos', sa.Column('movement_tags', sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    
    # PendingLogs KB snapshot columns
    op.add_column('pending_logs', sa.Column('kb_overhead_max_kg_at_time', sa.Integer(), nullable=True))
    op.add_column('pending_logs', sa.Column('kb_heavy_kg_at_time', sa.Integer(), nullable=True))
    op.add_column('pending_logs', sa.Column('kb_swing_kg_at_time', sa.Integer(), nullable=True))


def downgrade() -> None:
    # PendingLogs
    op.drop_column('pending_logs', 'kb_swing_kg_at_time')
    op.drop_column('pending_logs', 'kb_heavy_kg_at_time')
    op.drop_column('pending_logs', 'kb_overhead_max_kg_at_time')
    
    # Videos
    op.drop_column('videos', 'movement_tags')
    
    # Users CHECK constraints (skip on SQLite)
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite':
        op.drop_constraint('ck_users_kb_swing_kg', 'users', type_='check')
        op.drop_constraint('ck_users_kb_heavy_kg', 'users', type_='check')
        op.drop_constraint('ck_users_kb_overhead_max_kg', 'users', type_='check')
    
    # Users columns
    op.drop_column('users', 'kb_swing_kg')
    op.drop_column('users', 'kb_heavy_kg')
    op.drop_column('users', 'kb_overhead_max_kg')

