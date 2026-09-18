"""Validate/import media packages; script prose and old game snapshots stay unchanged."""

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from app.game.clues import normalize_clue_stages
from app.game.content_quality import content_fingerprint


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def checked_child(root, name):
    root = Path(root).resolve()
    path = (root / unquote(name)).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Resource path escapes its package")
    return path


def validate_package(source, package):
    package = Path(package).resolve()
    manifest = read_json(package / "manifest.json")
    if manifest.get("version") != 1 or manifest.get("script_id") != source.get("script_id"):
        raise ValueError("Unsupported package or mismatched script")
    expected = manifest["content_fingerprint"]
    if content_fingerprint(source) != expected:
        raise ValueError("Script text fingerprint does not match this package")
    stages = normalize_clue_stages(manifest["clue_stages"], script_id=source["script_id"])
    if content_fingerprint({**source, "clue_stages": stages}) != expected:
        raise ValueError("A media package must not change script text")
    urls = set()
    for stage in stages:
        config = stage.get("presentation")
        if config:
            if config["status"] != "ready":
                raise ValueError("Presentation requires review")
            covered = {id for shot in config["shots"] for id in shot["clue_ids"]}
            if set(item["id"] for item in stage["items"]) - covered:
                raise ValueError("Every stage clue must appear in the presentation")
        media = [item.get("media") for item in stage["items"]]
        media += [config.get("background")] if config else []
        for item in filter(None, media):
            if item["status"] != "ready":
                raise ValueError("Image requires review")
            urls.update((item["image_url"], item["thumbnail_url"]))
    files = {}
    for item in manifest["files"]:
        relative = item["path"]
        if not relative.startswith("images/") or relative in files:
            raise ValueError("Duplicate or invalid resource file")
        file = checked_child(package, relative)
        if hashlib.sha256(file.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError(f"Checksum mismatch: {relative}")
        files[relative] = file
    if {url.lstrip("/") for url in urls} - files.keys():
        raise ValueError("Referenced image missing from package")
    return manifest, stages, files


def import_package(source, package, images_root, database):
    manifest, stages, files = validate_package(source, package)
    database = Path(database).resolve(strict=True)
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        # Hold the writer reservation from fingerprint check through the update.
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM scripts WHERE script_id = ?", (source["script_id"],)
        ).fetchone()
        if row is None:
            raise ValueError("Script not found in target database")
        current = dict(row)
        current["characters"] = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM characters WHERE script_id = ?", (source["script_id"],)
            )
        ]
        if content_fingerprint(current) != manifest["content_fingerprint"]:
            raise ValueError("Target database text changed; import cancelled")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup = database.with_name(f"{database.name}.clue-media-{stamp}.bak")
        # A separate reader can back up the committed state while we reserve writes.
        with sqlite3.connect(database) as reader, sqlite3.connect(backup) as copy:
            reader.backup(copy)
        for relative, source_file in files.items():
            destination = checked_child(images_root, relative.removeprefix("images/"))
            if destination.exists():
                if destination.read_bytes() != source_file.read_bytes():
                    raise ValueError(f"Refusing to overwrite existing resource: {destination}")
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, destination)
        db.execute(
            "UPDATE scripts SET clue_stages = ? WHERE script_id = ?",
            (json.dumps(stages, ensure_ascii=False), source["script_id"]),
        )
        db.commit()
        return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "import"])
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--images-root", type=Path)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    source = read_json(args.source)
    manifest, stages, files = validate_package(source, args.package)
    if args.command == "import":
        if not args.images_root or not args.database:
            parser.error("import requires --images-root and --database")
        print(f"Backup: {import_package(source, args.package, args.images_root, args.database)}")
    print(
        json.dumps(
            {
                "script_id": manifest["script_id"],
                "stages": len(stages),
                "clues": sum(len(stage["items"]) for stage in stages),
                "files": len(files),
                "valid": True,
            }
        )
    )


if __name__ == "__main__":
    main()
