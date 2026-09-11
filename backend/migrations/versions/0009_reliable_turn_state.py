"""Persist unfinished reactions and canonicalize legacy belief keys."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "game_sessions", sa.Column("pending_speech", sa.JSON(), nullable=False, server_default="{}")
    )
    from app.agents.reaction import SuspectedByValue
    from app.agents.role_state import canonical_graph

    db = op.get_bind()
    rows = (
        db.execute(
            sa.text("SELECT id, session_id, suspicion_reasons, suspected_by FROM player_states")
        )
        .mappings()
        .all()
    )
    for row in rows:
        names = dict(
            db.execute(
                sa.text(
                    "SELECT c.character_id, c.name FROM characters c JOIN game_sessions g ON c.script_id=g.script_id WHERE g.session_id=:sid"
                ),
                {"sid": row["session_id"]},
            ).all()
        )
        snapshot = db.execute(
            sa.text("SELECT runtime_snapshot FROM game_sessions WHERE session_id=:sid"),
            {"sid": row["session_id"]},
        ).scalar()
        snapshot = json.loads(snapshot or "{}")
        if snapshot and snapshot.get("characters"):
            names = {c["character_id"]: c["name"] for c in snapshot["characters"]}
        suspicion = canonical_graph(json.loads(row["suspicion_reasons"] or "{}"), names)
        suspected = canonical_graph(
            json.loads(row["suspected_by"] or "{}"), names, model=SuspectedByValue
        )
        scores = [value["score"] for value in suspected.values()]
        db.execute(
            sa.text(
                "UPDATE player_states SET suspicion_reasons=:reasons, suspicion=:scores, suspected_by=:suspected, suspected_intensity=:intensity WHERE id=:id"
            ),
            {
                "id": row["id"],
                "reasons": json.dumps(suspicion),
                "scores": json.dumps({cid: value["score"] for cid, value in suspicion.items()}),
                "suspected": json.dumps(suspected),
                "intensity": sum(scores) / len(scores) if scores else 0.0,
            },
        )


def downgrade():
    op.drop_column("game_sessions", "pending_speech")
