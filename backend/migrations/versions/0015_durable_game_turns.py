"""Keep speech operations and their message identity across disconnected clients."""

import sqlalchemy as sa
from alembic import op

revision = "0015_game_turns"
down_revision = "0014_speech_generation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "game_sessions",
        sa.Column("state_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("game_records", sa.Column("turn_id", sa.String(64), nullable=True))
    op.create_index("ix_game_records_turn_id", "game_records", ["turn_id"], unique=True)
    op.create_table(
        "game_turns",
        sa.Column("turn_id", sa.String(64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("game_sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("speaker_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generation_done", sa.Boolean(), nullable=False),
        sa.Column("thinking_tip", sa.Text(), nullable=False),
        sa.Column("clue_refs", sa.JSON(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("input_checkpoint_id", sa.String(100), nullable=True),
        sa.Column("attempt_state", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_game_turns_session_id", "game_turns", ["session_id"])


def downgrade():
    op.drop_table("game_turns")
    op.drop_index("ix_game_records_turn_id", table_name="game_records")
    op.drop_column("game_records", "turn_id")
    op.drop_column("game_sessions", "state_revision")
