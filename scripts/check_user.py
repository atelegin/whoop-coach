#!/usr/bin/env python3
"""Quick script to check user's whoop_user_id."""

import asyncio
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import select, text
from whoop_coach.db.session import async_session_factory
from whoop_coach.db.models import User


async def main():
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                User.telegram_id, 
                User.whoop_user_id,
                User.whoop_tokens_enc != None,  # noqa: E711
            )
        )
        rows = result.all()
        
        print("\n=== Users in database ===")
        for row in rows:
            print(f"telegram_id={row[0]}, whoop_user_id={row[1]!r}, has_tokens={row[2]}")
        
        if not rows:
            print("No users found!")


if __name__ == "__main__":
    asyncio.run(main())
