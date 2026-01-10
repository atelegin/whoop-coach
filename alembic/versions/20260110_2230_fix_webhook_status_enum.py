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
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '3a4b5c6d7e8f'
down_revision: Union[str, None] = '20260106_1606_whoop_snapshot'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    
    # Check current column type
    result = conn.execute(text("""
        SELECT data_type FROM information_schema.columns 
        WHERE table_name = 'whoop_webhook_events' AND column_name = 'status'
    """))
    row = result.fetchone()
    current_type = row[0] if row else None
    
    # If already enum (USER-DEFINED), skip migration
    if current_type == 'USER-DEFINED':
        print("[Migration] status column is already enum type, skipping")
        return
    
    # 1. Drop the default FIRST (required before type change)
    # Use IF EXISTS pattern via catching exception
    try:
        conn.execute(text("""
            ALTER TABLE whoop_webhook_events 
            ALTER COLUMN status DROP DEFAULT
        """))
    except Exception:
        pass  # Default might already be dropped
    
    # 2. Create the enum type IF NOT EXISTS
    result = conn.execute(text("""
        SELECT 1 FROM pg_type WHERE typname = 'webhookeventstatus'
    """))
    if not result.fetchone():
        conn.execute(text("""
            CREATE TYPE webhookeventstatus AS ENUM (
                'pending', 'processing', 'pending_score', 
                'awaiting_feedback', 'done', 'failed'
            )
        """))
    
    # 3. Convert the column from varchar to enum
    conn.execute(text("""
        ALTER TABLE whoop_webhook_events 
        ALTER COLUMN status TYPE webhookeventstatus 
        USING status::webhookeventstatus
    """))


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
    op.execute("DROP TYPE IF EXISTS webhookeventstatus")
