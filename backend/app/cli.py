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


async def _probe_models(selected: str | None) -> None:
    from app.core.llm_factory import create_llm
    from app.core.model_registry import MODEL_SPECS, save_probe_result

    specs = [spec for spec in MODEL_SPECS if selected is None or spec.id == selected]
    if selected and not specs:
        raise ValueError(f"Unknown model: {selected}")
    for spec in specs:
        if not settings.get_api_key(spec.provider):
            print(f"SKIP {spec.id}: missing {spec.provider} API key")
            continue
        try:
            model = create_llm(
                model=spec.id,
                temperature=0,
                timeout=30,
                max_retries=0,
                disable_thinking=True,
            )
            response = await model.ainvoke("只回复 OK")
            ok = bool(getattr(response, "content", ""))
            save_probe_result(spec.id, ok=ok, error="" if ok else "empty response")
            print(f"{'OK' if ok else 'FAIL'} {spec.id}")
        except Exception as exc:
            save_probe_result(spec.id, ok=False, error=str(exc))
            print(f"FAIL {spec.id}: {exc}")


def probe_models(selected: str | None = None) -> None:
    asyncio.run(_probe_models(selected))


def migrate_clues(
    *, apply: bool, script_ids: list[str], manifest: Path | None, force: bool
) -> None:
    from app.script_editor.clue_migration import backup_database, migrate_legacy_clues

    if apply:
        backup = backup_database(_database_path())
        print(f"Database backup: {backup}")
    asyncio.run(
        migrate_legacy_clues(
            apply=apply,
            script_ids=script_ids or None,
            manifest_path=manifest,
            force=force,
        )
    )


def regenerate_clue_audio(script_ids: list[str]) -> None:
    from app.script_editor.clue_migration import regenerate_clue_tts

    asyncio.run(regenerate_clue_tts(script_ids or None))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sober Alone local data management")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Upgrade the database and seed an empty installation")
    adopt = subparsers.add_parser(
        "adopt-legacy-db", help="Back up and adopt a private legacy SQLite database"
    )
    adopt.add_argument("--path", type=Path, default=None, help="Legacy database path")
    probe = subparsers.add_parser(
        "probe-models", help="Verify configured OpenAI-compatible chat models"
    )
    probe.add_argument("--model", default=None, help="Probe only one exact model ID")
    clues = subparsers.add_parser(
        "migrate-clues", help="Convert legacy clue messages (dry-run by default)"
    )
    clues.add_argument("--apply", action="store_true", help="Write validated results")
    clues.add_argument("--script-id", action="append", default=[])
    clues.add_argument("--manifest", type=Path, default=None)
    clues.add_argument("--force", action="store_true")
    clue_tts = subparsers.add_parser(
        "regenerate-clue-tts", help="Back up and regenerate only clue-stage audio"
    )
    clue_tts.add_argument("--script-id", action="append", default=[])
    args = parser.parse_args()

    if args.command == "init":
        init()
    elif args.command == "adopt-legacy-db":
        adopt_legacy_db(args.path)
    elif args.command == "probe-models":
        probe_models(args.model)
    elif args.command == "migrate-clues":
        migrate_clues(
            apply=args.apply,
            script_ids=args.script_id,
            manifest=args.manifest,
            force=args.force,
        )
    elif args.command == "regenerate-clue-tts":
        regenerate_clue_audio(args.script_id)


if __name__ == "__main__":
    main()
