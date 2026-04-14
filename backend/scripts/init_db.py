"""Initialize database tables including pilot_metrics.

Run after docker-compose up:
    python scripts/init_db.py

Creates all SQLAlchemy ORM tables (sessions, note_versions, pilot_metrics)
if they do not already exist. Safe to run multiple times -- existing tables
are not dropped or modified.
"""

import asyncio
import sys
from pathlib import Path

# Ensure the backend package is importable when running from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import Base, engine  # noqa: E402
from app.core.models import NoteVersionModel, PilotMetricsModel, SessionModel  # noqa: E402


async def init() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("All tables created successfully.")
    print(f"  - {SessionModel.__tablename__}")
    print(f"  - {NoteVersionModel.__tablename__}")
    print(f"  - {PilotMetricsModel.__tablename__}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init())
