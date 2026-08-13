"""Local database lifecycle commands.

Usage:
    python -m app.cli init
    python -m app.cli adopt-legacy-db [--path path/to/game_data.db]
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.core.config import BACKEND_ROOT, settings

BUSINESS_TABLES = {"scripts", "characters", "game_sessions", "player_states", "game_records"}


def _database_path() -> Path:
    database = make_url(settings.DATABASE_URL).database
    if not database:
        raise RuntimeError("DATABASE_URL must point to a SQLite database")
    return Path(database).resolve()


def _alembic_config() -> Config:
    return Config(str(BACKEND_ROOT / "alembic.ini"))


def _prepare_directories() -> None:
    for path in (
        settings.local_data_dir,
        settings.audio_dir,
        settings.image_dir,
        Path(settings.CHROMA_PERSIST_DIR),
    ):
        path.mkdir(parents=True, exist_ok=True)
    _database_path().parent.mkdir(parents=True, exist_ok=True)


async def _seed() -> bool:
    from app.db.session import AsyncSessionLocal
    from app.seed import seed_sample_if_empty

    async with AsyncSessionLocal() as session:
        return await seed_sample_if_empty(session)


def init() -> None:
    _prepare_directories()
    command.upgrade(_alembic_config(), "head")
    inserted = asyncio.run(_seed())
    print("Database ready.")
    print("Sample imported." if inserted else "Existing scripts kept; sample import skipped.")


def adopt_legacy_db(source: Path | None) -> None:
    source = (source or (BACKEND_ROOT / "data" / "game_data.db")).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Legacy database not found: {source}")

    with sqlite3.connect(source) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    missing = BUSINESS_TABLES - tables
    if missing:
        raise RuntimeError(
            f"Legacy database is missing required tables: {', '.join(sorted(missing))}"
        )

    target = _database_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = source.with_name(f"{source.name}.{timestamp}.bak")
    shutil.copy2(source, backup)
    if source != target:
        shutil.copy2(source, target)

    config = _alembic_config()
    command.stamp(config, "0001")
    command.upgrade(config, "head")
    print(f"Legacy database adopted: {target}")
    print(f"Backup preserved: {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sober Alone local data management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Upgrade the database and seed an empty installation")
    adopt = subparsers.add_parser(
        "adopt-legacy-db", help="Back up and adopt a private legacy SQLite database"
    )
    adopt.add_argument("--path", type=Path, default=None, help="Legacy database path")
    args = parser.parse_args()

    if args.command == "init":
        init()
    elif args.command == "adopt-legacy-db":
        adopt_legacy_db(args.path)


if __name__ == "__main__":
    main()
