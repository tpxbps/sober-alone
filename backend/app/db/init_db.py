"""Database initialization script"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.db.base import Base
from app.db.models import game_session, game_record
from app.core.config import settings


# Create async engine
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
)


async def init_db():
    """Create all tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created successfully!")


async def drop_db():
    """Drop all tables (use with caution)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("Database tables dropped!")


async def reset_db():
    """Drop and recreate all tables"""
    await drop_db()
    await init_db()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Database management")
    parser.add_argument("--init", action="store_true", help="Initialize database")
    parser.add_argument("--drop", action="store_true", help="Drop database tables")
    parser.add_argument("--reset", action="store_true", help="Reset database (drop + init)")

    args = parser.parse_args()

    if args.init:
        asyncio.run(init_db())
    elif args.drop:
        asyncio.run(drop_db())
    elif args.reset:
        asyncio.run(reset_db())
    else:
        parser.print_help()
