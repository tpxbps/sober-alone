import hashlib
import json
import sqlite3

import pytest
from test_clue_presentation import stages

from app.game.content_quality import content_fingerprint
from scripts.clue_media import checked_child, import_package, validate_package


def test_verified_import_preserves_prose_old_sessions_and_existing_assets(tmp_path):
    source = {"script_id": "s", "title": "测试", "clue_stages": stages()}
    package = tmp_path / "package"
    package.mkdir()
    files = []
    for name in ("paper.webp", "paper-small.webp"):
        relative = "images/scripts/test/" + name
        file = package / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"test resource checksum")
        files.append({"path": relative, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    manifest = {
        "version": 1,
        "script_id": "s",
        "content_fingerprint": content_fingerprint(source),
        "clue_stages": source["clue_stages"],
        "files": files,
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    database = tmp_path / "game.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE scripts (script_id TEXT, title TEXT, clue_stages TEXT)")
        db.execute("CREATE TABLE characters (script_id TEXT, character_id TEXT)")
        db.execute("CREATE TABLE game_sessions (runtime_snapshot TEXT)")
        db.execute(
            "INSERT INTO scripts VALUES (?, ?, ?)", ("s", "测试", json.dumps(source["clue_stages"]))
        )
        db.execute("INSERT INTO game_sessions VALUES (?)", ("old immutable snapshot",))
    backup = import_package(source, package, tmp_path / "images", database)
    assert backup.is_file()
    with sqlite3.connect(database) as db:
        assert (
            db.execute("SELECT runtime_snapshot FROM game_sessions").fetchone()[0]
            == "old immutable snapshot"
        )
        row = db.execute("SELECT title, clue_stages FROM scripts").fetchone()
        assert (
            content_fingerprint({"title": row[0], "clue_stages": json.loads(row[1])})
            == manifest["content_fingerprint"]
        )
        db.execute("UPDATE scripts SET title = '正文已变化'")
    with pytest.raises(ValueError, match="text changed"):
        import_package(source, package, tmp_path / "images", database)
    (package / files[0]["path"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="Checksum"):
        validate_package(source, package)
    with pytest.raises(ValueError, match="escapes"):
        checked_child(package, "../outside")
