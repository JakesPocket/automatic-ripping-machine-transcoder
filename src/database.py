"""
Database setup and session management
"""

import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from config import settings
from models import Base

# Ensure database directory exists
os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)

# Create async engine
engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.db_path}",
    echo=False,
)

# Session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Initialize database tables and add any missing columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add columns that may be missing in existing databases.
        # SQLite's CREATE_ALL won't alter existing tables.
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(conn):
    """Add columns to existing tables if they don't exist yet."""
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    if "transcode_jobs" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("transcode_jobs")}
        migrations = [
            ("disctype", "VARCHAR(50)"),
            ("logfile", "VARCHAR(255)"),
            ("poster_url", "VARCHAR(500)"),
            ("config_overrides", "TEXT"),
        ]
        for col_name, col_type in migrations:
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE transcode_jobs ADD COLUMN {col_name} {col_type}"
                ))


@asynccontextmanager
async def get_db():
    """Get database session context manager."""
    async with async_session() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
