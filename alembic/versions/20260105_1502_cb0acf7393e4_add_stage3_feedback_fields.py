"""add_stage3_feedback_fields

Revision ID: cb0acf7393e4
Revises: 636804fc1463
Create Date: 2026-01-05 15:02:25.646813+00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'cb0acf7393e4'
down_revision: Union[str, None] = '636804fc1463'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns (all nullable or with defaults for SQLite compatibility)
    op.add_column('feedback', sa.Column('soreness_0_3', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('pain_locations', sa.JSON(), nullable=True))
    op.add_column('feedback', sa.Column('feedback_date', sa.Date(), nullable=True))
    op.add_column('feedback', sa.Column('is_morning_prompt', sa.Boolean(), nullable=False, server_default=sa.text('0')))
    
    # Note: SQLite doesn't support adding constraints with ALTER TABLE
    # The unique constraint is enforced at the application level for SQLite
    # For PostgreSQL in production, uncomment:
    # op.create_unique_constraint('uq_feedback_user_date_morning', 'feedback', 
    #                             ['user_id', 'feedback_date', 'is_morning_prompt'])


def downgrade() -> None:
    op.drop_column('feedback', 'is_morning_prompt')
    op.drop_column('feedback', 'feedback_date')
    op.drop_column('feedback', 'pain_locations')
    op.drop_column('feedback', 'soreness_0_3')
