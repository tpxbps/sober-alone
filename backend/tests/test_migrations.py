import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.seed import SAMPLE_SCRIPT_ID

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_compact_clue_migration_can_repair_legacy_runtime_snapshot_ids():
    migration = importlib.import_module("migrations.versions.0004_compact_inline_clue_references")
    stages, mapping = migration._compact_stages(
        [
            {
                "stage": 1,
                "overview": "第一轮",
                "items": [
                    {
                        "id": "clue-123456789abc",
                        "summary": "门锁",
                        "content": "门锁没有撬动痕迹。",
                        "stage": 1,
                    }
                ],
            }
        ]
    )
    snapshot = migration._rewrite_json(
        {
            "clue_stages": stages,
            "game_full_process": [{"system_notice": "门锁没有撬动痕迹。[clue-123456789abc]"}],
        },
        mapping,
    )

    assert mapping == {"clue-123456789abc": "c01"}
    assert snapshot["clue_stages"][0]["items"][0]["id"] == "c01"
    assert snapshot["game_full_process"][0]["system_notice"].endswith("[c01]")


def test_init_is_idempotent(tmp_path: Path):
    database = tmp_path / "game.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"
    env["DEEPSEEK_API_KEY"] = ""
    env["STEPFUN_API_KEY"] = ""

    first = subprocess.run(
        [sys.executable, "-m", "app.cli", "init"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=BACKEND_ROOT,
    )
    second = subprocess.run(
        [sys.executable, "-m", "app.cli", "init"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
        cwd=BACKEND_ROOT,
    )

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        script_count = connection.execute(
            "SELECT COUNT(*) FROM scripts WHERE script_id = ?", (SAMPLE_SCRIPT_ID,)
        ).fetchone()[0]
        character_count = connection.execute(
            "SELECT COUNT(*) FROM characters WHERE script_id = ?", (SAMPLE_SCRIPT_ID,)
        ).fetchone()[0]
        script_columns = {row[1] for row in connection.execute("PRAGMA table_info(scripts)")}
        player_state_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(player_states)")
        }
        game_session_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(game_sessions)")
        }
        game_record_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(game_records)")
        }
        legacy_owner = connection.execute(
            "SELECT owner_key_hash FROM scripts WHERE script_id = ?", (SAMPLE_SCRIPT_ID,)
        ).fetchone()[0]

    assert {
        "scripts",
        "characters",
        "game_sessions",
        "player_states",
        "game_records",
        "editor_workflows",
        "editor_operations",
        "script_feedback",
    } <= tables
    assert script_count == 1
    assert character_count == 4
    assert "owner_key_hash" in script_columns
    assert {
        "clue_stages",
        "clue_schema_version",
        "content_fingerprint",
        "ai_review",
        "quality_report",
    } <= script_columns
    assert "last_seen_human_record_id" in player_state_columns
    assert {
        "runtime_snapshot",
        "revealed_clues",
        "last_active_at",
        "reviewer_hash",
    } <= game_session_columns
    assert "clue_refs" in game_record_columns
    assert legacy_owner is None
    assert "Sample imported" in first.stdout
    assert "sample import skipped" in second.stdout

    # Exercise the public pre-feature schema with real rows, then upgrade again.
    for revision in ("0004", "head"):
        command = "downgrade" if revision == "0004" else "upgrade"
        subprocess.run(
            [sys.executable, "-m", "alembic", command, revision],
            check=True,
            capture_output=True,
            env=env,
            cwd=BACKEND_ROOT,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM characters").fetchone()[0] == 4
        assert connection.execute(
            "SELECT content_fingerprint, ai_review FROM scripts WHERE script_id=?",
            (SAMPLE_SCRIPT_ID,),
        ).fetchone() == (None, None)
        assert connection.execute("SELECT count(*) FROM script_feedback").fetchone()[0] == 0
