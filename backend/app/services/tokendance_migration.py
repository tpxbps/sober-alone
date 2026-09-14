"""Build a separate gateway index and a reviewable voice migration manifest.

Run with python -m app.services.tokendance_migration. Database writes require
--apply-voices; the vector destination must differ from the active index.
"""

import argparse
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from app.core.config import settings
from app.rag.embeddings import profile
from app.rag.retriever import ChromaRetriever
from app.rag.revision import script_digest
from app.script_editor.services.chroma_ingest import ingest_character
from app.services.voices import VOICE_IDS, resolve_minimax_voice


def _read_rows(db: sqlite3.Connection) -> list[dict]:
    db.row_factory = sqlite3.Row
    return [
        dict(row)
        for row in db.execute(
            "SELECT character_id, script_id, name, gender, age, occupation, profile, "
            "character_script, voice_id FROM characters ORDER BY script_id, character_id"
        )
    ]


def source_rows(database: Path) -> list[dict]:
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        return _read_rows(db)


def manifest_for(rows: list[dict]) -> dict:
    entries = [
        {
            "script_id": row["script_id"],
            "character_id": row["character_id"],
            "name": row["name"],
            "content_digest": script_digest(row["character_script"] or ""),
            "old_voice": row["voice_id"],
            "voice_id": resolve_minimax_voice(row["voice_id"], row),
            "voice_provider": "minimax",
        }
        for row in rows
    ]
    return {
        "embedding_profile": profile(),
        "characters": entries,
        "source_digest": hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
    }


async def build(database: Path, destination: Path) -> dict:
    active = Path(settings.CHROMA_PERSIST_DIR).resolve()
    if destination.resolve() == active or active in destination.resolve().parents:
        raise ValueError("Build into a separate directory, never overwrite the active index")
    if settings.INFERENCE_BACKEND != "tokendance":
        raise ValueError("Set INFERENCE_BACKEND=tokendance before building")
    rows = source_rows(database)
    if not rows:
        raise ValueError("No characters found")
    destination.mkdir(parents=True, exist_ok=True)
    previous = settings.CHROMA_PERSIST_DIR
    settings.CHROMA_PERSIST_DIR = str(destination.resolve())
    try:
        retriever = ChromaRetriever(str(destination))
        for row in rows:
            text = row["character_script"] or ""
            if not text:
                raise ValueError(f"Missing personal script: {row['character_id']}")
            digest = script_digest(text)
            if not await retriever.character_index_ready(
                row["script_id"], row["character_id"], digest
            ):
                await asyncio.to_thread(ingest_character, row["script_id"], row, text)
            if not await retriever.character_index_ready(
                row["script_id"], row["character_id"], digest
            ):
                raise RuntimeError(f"Incomplete index: {row['character_id']}")
        result = manifest_for(rows)
        if manifest_for(source_rows(database))["source_digest"] != result["source_digest"]:
            raise RuntimeError("Source changed during build; repeat to catch up")
        (destination / "migration-manifest.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result
    finally:
        settings.CHROMA_PERSIST_DIR = previous


def apply_voices(database: Path, manifest: dict) -> None:
    rows = source_rows(database)
    expected = manifest_for(rows)
    if expected["source_digest"] != manifest["source_digest"]:
        raise ValueError("Source changed; rebuild and review the manifest again")
    if manifest["embedding_profile"] != expected["embedding_profile"]:
        raise ValueError("Embedding profile changed")

    def identity(entry):
        return (entry["script_id"], entry["character_id"], entry["content_digest"])

    if sorted(map(identity, manifest["characters"])) != sorted(
        map(identity, expected["characters"])
    ):
        raise ValueError("Manifest must contain every source character exactly once")
    if any(row["voice_id"] not in VOICE_IDS for row in manifest["characters"]):
        raise ValueError("Manifest contains an unsupported voice")
    backup = database.with_name(database.name + ".before-tokendance")
    if backup.exists():
        raise ValueError("Voice backup already exists; preserve it before retrying")
    with sqlite3.connect(database) as db, sqlite3.connect(backup) as copy:
        db.backup(copy)
        if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
        with db:
            db.execute("BEGIN IMMEDIATE")
            if manifest_for(_read_rows(db))["source_digest"] != expected["source_digest"]:
                raise ValueError("Source changed before migration; rebuild the manifest")
            for row in manifest["characters"]:
                cursor = db.execute(
                    "UPDATE characters SET voice_id=?, voice_provider=? WHERE character_id=?",
                    (row["voice_id"], "minimax", row["character_id"]),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Character disappeared during migration")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--apply-voices", action="store_true")
    args = parser.parse_args()
    if args.build:
        manifest = asyncio.run(build(args.database, args.output))
    elif args.apply_voices:
        manifest = json.loads((args.output / "migration-manifest.json").read_text(encoding="utf-8"))
    else:
        manifest = manifest_for(source_rows(args.database))
    if args.apply_voices:
        apply_voices(args.database, manifest)
    print(
        json.dumps(
            {
                "characters": len(manifest["characters"]),
                "source_digest": manifest["source_digest"],
                "applied": args.apply_voices,
            }
        )
    )


if __name__ == "__main__":
    main()
