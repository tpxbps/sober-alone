import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.seed import SAMPLE_SCRIPT_ID

BACKEND_ROOT = Path(__file__).resolve().parents[1]


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

    assert {"scripts", "characters", "game_sessions", "player_states", "game_records"} <= tables
    assert script_count == 1
    assert character_count == 4
    assert "Sample imported" in first.stdout
    assert "sample import skipped" in second.stdout
