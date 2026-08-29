"""Compact clue IDs and keep citations inline with their supporting prose.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_TAG_RE = re.compile(r"\[((?:c[0-9]{2,4})|(?:clue-[a-z0-9]{12}))\]", re.IGNORECASE)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _compact_stages(value: Any) -> tuple[list[dict], dict[str, str]]:
    stages = _json_value(value, [])
    mapping: dict[str, str] = {}
    ordinal = 1
    for stage in stages:
        for item in stage.get("items", []) or []:
            old_id = str(item.get("id") or "").strip().lower()
            new_id = f"c{ordinal:02d}"
            ordinal += 1
            if old_id:
                mapping[old_id] = new_id
            item["id"] = new_id
    return stages, mapping


def _rewrite_tags(text: str | None, mapping: dict[str, str]) -> str:
    value = text or ""

    def replace(match: re.Match[str]) -> str:
        clue_id = match.group(1).lower()
        return f"[{mapping.get(clue_id, clue_id)}]"

    return _TAG_RE.sub(replace, value)


def _rewrite_json(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [_rewrite_json(item, mapping) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                mapping.get(item.lower(), item)
                if key == "id" and isinstance(item, str)
                else _rewrite_json(item, mapping)
            )
            for key, item in value.items()
        }
    if isinstance(value, str):
        return _rewrite_tags(value, mapping)
    return value


def upgrade() -> None:
    connection = op.get_bind()
    mappings: dict[str, dict[str, str]] = {}

    for row in connection.execute(
        sa.text("SELECT script_id, clue_stages, game_full_process FROM scripts")
    ):
        script_id = row._mapping["script_id"]
        stages, mapping = _compact_stages(row._mapping["clue_stages"])
        mappings[script_id] = mapping
        process = _rewrite_json(_json_value(row._mapping["game_full_process"], []), mapping)
        connection.execute(
            sa.text(
                "UPDATE scripts SET clue_stages=:stages, clue_schema_version=2, "
                "game_full_process=:process WHERE script_id=:script_id"
            ),
            {
                "stages": json.dumps(stages, ensure_ascii=False),
                "process": json.dumps(process, ensure_ascii=False),
                "script_id": script_id,
            },
        )

    session_mappings: dict[str, dict[str, str]] = {}
    for row in connection.execute(
        sa.text("SELECT session_id, script_id, runtime_snapshot, revealed_clues FROM game_sessions")
    ):
        session_id = row._mapping["session_id"]
        script_id = row._mapping["script_id"]
        snapshot = _json_value(row._mapping["runtime_snapshot"], {})
        # 0003 intentionally kept script rows untouched but placed deterministic
        # legacy clues in each immutable runtime snapshot.  When a script does
        # not yet have structured clues, compact the snapshot's own IDs so an
        # in-flight upgraded game never exposes the former long hash IDs.
        snapshot_stages, snapshot_mapping = _compact_stages(snapshot.get("clue_stages", []))
        mapping = mappings.get(script_id, {}) or snapshot_mapping
        session_mappings[session_id] = mapping
        snapshot["clue_stages"] = _rewrite_json(snapshot_stages, mapping)
        snapshot = _rewrite_json(snapshot, mapping)
        if snapshot:
            snapshot["clue_schema_version"] = 2
        revealed = _rewrite_json(_json_value(row._mapping["revealed_clues"], []), mapping)
        connection.execute(
            sa.text(
                "UPDATE game_sessions SET runtime_snapshot=:snapshot, "
                "revealed_clues=:revealed WHERE session_id=:session_id"
            ),
            {
                "snapshot": json.dumps(snapshot, ensure_ascii=False),
                "revealed": json.dumps(revealed, ensure_ascii=False),
                "session_id": session_id,
            },
        )

    for row in connection.execute(
        sa.text("SELECT id, session_id, raw_content, clue_refs FROM game_records")
    ):
        mapping = session_mappings.get(row._mapping["session_id"], {})
        refs = [
            mapping.get(str(ref).lower(), str(ref).lower())
            for ref in _json_value(row._mapping["clue_refs"], [])
        ]
        content = _rewrite_tags(row._mapping["raw_content"], mapping)
        # Metadata-only references have no trustworthy sentence position. Keep
        # them for auditing/querying, but never invent a visible citation location.
        connection.execute(
            sa.text("UPDATE game_records SET raw_content=:content, clue_refs=:refs WHERE id=:id"),
            {
                "content": content,
                "refs": json.dumps(refs, ensure_ascii=False),
                "id": row._mapping["id"],
            },
        )


def downgrade() -> None:
    # Compact IDs are valid in the compatibility reader and cannot be expanded
    # back to their former hashes without keeping duplicate data indefinitely.
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE scripts SET clue_schema_version=1"))
