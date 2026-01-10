"""fix_webhook_status_enum

Revision ID: 3a4b5c6d7e8f
Revises: 20260106_1606_whoop_snapshot
Create Date: 2026-01-10 22:30:00.000000+00:00

Fix: Convert status column from String to Enum type.
The original migration created status as String(20), but the model
uses Enum(WebhookEventStatus). This caused:
  type "webhookeventstatus" does not exist
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3a4b5c6d7e8f'
down_revision: Union[str, None] = '20260106_1606_whoop_snapshot'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the enum type
    op.execute("""
        CREATE TYPE webhookeventstatus AS ENUM (
            'pending', 'processing', 'pending_score', 
            'awaiting_feedback', 'done', 'failed'
        )
    """)
    
    # 2. Convert the column from varchar to enum
    op.execute("""
        ALTER TABLE whoop_webhook_events 
        ALTER COLUMN status TYPE webhookeventstatus 
        USING status::webhookeventstatus
    """)
    
    # 3. Remove the default (it was 'pending' as string, now we set it in app)
    op.execute("""
        ALTER TABLE whoop_webhook_events 
        ALTER COLUMN status DROP DEFAULT
    """)


def downgrade() -> None:
    # Convert back to varchar
    op.execute("""
        ALTER TABLE whoop_webhook_events 
        ALTER COLUMN status TYPE VARCHAR(20) 
        USING status::text
    """)
    
    # Set default back
    op.execute("""
        ALTER TABLE whoop_webhook_events 
        ALTER COLUMN status SET DEFAULT 'pending'
    """)
    
    # Drop the enum type
    op.execute("DROP TYPE webhookeventstatus")
