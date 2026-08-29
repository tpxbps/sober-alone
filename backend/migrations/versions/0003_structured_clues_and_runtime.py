"""Add structured clues, immutable game snapshots and durable workflow operations.

Revision ID: 0003
Revises: 0002
"""

import hashlib
import json
import re

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _json_value(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else fallback
    except (TypeError, json.JSONDecodeError):
        return fallback


def _legacy_clues(script_id: str, process: list[dict]) -> list[dict]:
    stages = []
    round_number = 0
    for stage in process:
        if stage.get("type") != "advancement":
            continue
        round_number += 1
        children = stage.get("children") or []
        text = str(children[0].get("system_notice", "")) if children else ""
        if not text.strip():
            continue
        compact = " ".join(text.replace("#", " ").replace("*", " ").split())
        summary = re.split(r"[。！？!?\n]", compact, maxsplit=1)[0].strip()[:48]
        digest = hashlib.sha256(f"{script_id}:{round_number}:legacy".encode()).hexdigest()[:12]
        stages.append(
            {
                "stage": round_number,
                "overview": f"第 {round_number} 轮公开线索",
                "items": [
                    {
                        "id": f"clue-{digest}",
                        "summary": summary or f"第 {round_number} 轮公开线索",
                        "content": text.strip(),
                        "stage": round_number,
                    }
                ],
                "free_discussion_notice": (
                    str(children[1].get("system_notice", "")) if len(children) > 1 else ""
                ),
            }
        )
    return stages


def _backfill_game_snapshots() -> None:
    connection = op.get_bind()
    scripts = {
        row._mapping["script_id"]: dict(row._mapping)
        for row in connection.execute(sa.text("SELECT * FROM scripts"))
    }
    characters: dict[str, list[dict]] = {}
    for row in connection.execute(sa.text("SELECT * FROM characters ORDER BY character_id")):
        item = dict(row._mapping)
        characters.setdefault(item["script_id"], []).append(item)
    sessions = list(
        connection.execute(
            sa.text(
                "SELECT session_id, script_id, current_round, current_stage, "
                "updated_at, created_at FROM game_sessions"
            )
        )
    )
    allowed_script_fields = (
        "script_id",
        "title",
        "overview",
        "description",
        "tags",
        "difficulty",
        "player_count",
        "estimated_duration",
        "game_full_process",
        "full_truth",
        "cover_image_url",
        "free_speech_limits",
    )
    allowed_character_fields = (
        "character_id",
        "script_id",
        "name",
        "gender",
        "age",
        "occupation",
        "character_script",
        "character_script_summary",
        "profile",
        "appearance",
        "system_prompt",
        "avatar_url",
        "portrait_url",
        "voice_id",
    )
    for row in sessions:
        session = row._mapping
        script = scripts.get(session["script_id"])
        if not script:
            continue
        process = _json_value(script.get("game_full_process"), [])
        stages = _legacy_clues(script["script_id"], process)
        snapshot = {field: script.get(field) for field in allowed_script_fields}
        snapshot["game_full_process"] = process
        snapshot["free_speech_limits"] = _json_value(snapshot.get("free_speech_limits"), [])
        snapshot["clue_stages"] = stages
        snapshot["clue_schema_version"] = 0
        snapshot["characters"] = [
            {field: character.get(field) for field in allowed_character_fields}
            for character in characters.get(script["script_id"], [])
        ]
        snapshot["llm_configs"] = {}
        revealed = [
            item
            for clue_stage in stages
            if int(clue_stage["stage"]) <= int(session["current_round"] or 0)
            for item in clue_stage["items"]
        ]
        connection.execute(
            sa.text(
                "UPDATE game_sessions SET runtime_snapshot=:snapshot, "
                "revealed_clues=:revealed, last_active_at=:last_active "
                "WHERE session_id=:session_id"
            ),
            {
                "snapshot": json.dumps(snapshot, ensure_ascii=False),
                "revealed": json.dumps(revealed, ensure_ascii=False),
                "last_active": session["updated_at"] or session["created_at"],
                "session_id": session["session_id"],
            },
        )


def upgrade() -> None:
    op.add_column(
        "scripts", sa.Column("clue_stages", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column(
        "scripts",
        sa.Column("clue_schema_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "game_sessions",
        sa.Column("runtime_snapshot", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "game_sessions",
        sa.Column("revealed_clues", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "game_sessions",
        sa.Column("last_active_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "game_records", sa.Column("clue_refs", sa.JSON(), nullable=False, server_default="[]")
    )
    op.create_table(
        "editor_workflows",
        sa.Column("thread_id", sa.String(length=36), primary_key=True),
        sa.Column("owner_key_hash", sa.String(length=64), nullable=False),
        sa.Column("workflow_mode", sa.String(length=10), nullable=False),
        sa.Column("script_id", sa.String(length=64), nullable=True),
        sa.Column("current_step", sa.String(length=64), nullable=False, server_default="init"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "editor_operations",
        sa.Column("operation_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(length=36),
            sa.ForeignKey("editor_workflows.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("target_step", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("request_payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("progress", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_editor_operations_thread_status",
        "editor_operations",
        ["thread_id", "status"],
    )
    _backfill_game_snapshots()


def downgrade() -> None:
    op.drop_index("ix_editor_operations_thread_status", table_name="editor_operations")
    op.drop_table("editor_operations")
    op.drop_table("editor_workflows")
    op.drop_column("game_records", "clue_refs")
    op.drop_column("game_sessions", "last_active_at")
    op.drop_column("game_sessions", "revealed_clues")
    op.drop_column("game_sessions", "runtime_snapshot")
    op.drop_column("scripts", "clue_schema_version")
    op.drop_column("scripts", "clue_stages")
