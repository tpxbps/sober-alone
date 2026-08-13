"""Create the five local business tables.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scripts",
        sa.Column("script_id", sa.String(64), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.String(500), nullable=False, server_default=""),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("player_count", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("estimated_duration", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("game_full_process", sa.JSON(), nullable=False),
        sa.Column("full_truth", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_image_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("free_speech_limits", sa.JSON(), nullable=False),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "characters",
        sa.Column("character_id", sa.String(64), primary_key=True),
        sa.Column("script_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("gender", sa.String(20), nullable=False, server_default=""),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("occupation", sa.String(100), nullable=False, server_default=""),
        sa.Column("character_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("character_script_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("profile", sa.Text(), nullable=False, server_default=""),
        sa.Column("appearance", sa.Text(), nullable=False, server_default=""),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("avatar_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("portrait_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("voice_id", sa.String(100), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.script_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "game_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("script_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_stage", sa.String(30), nullable=False),
        sa.Column("current_round", sa.Integer(), nullable=False),
        sa.Column("player_threads", sa.JSON(), nullable=False),
        sa.Column("player_types", sa.JSON(), nullable=False),
        sa.Column("human_character_id", sa.String(36), nullable=True),
        sa.Column("speech_queue", sa.JSON(), nullable=False),
        sa.Column("current_speaker", sa.String(36), nullable=True),
        sa.Column("round_speakers", sa.JSON(), nullable=False),
        sa.Column("votes", sa.JSON(), nullable=False),
        sa.Column("final_suspect_id", sa.String(36), nullable=True),
        sa.Column("final_suspect_name", sa.String(50), nullable=True),
        sa.Column("vote_result", sa.JSON(), nullable=False),
        sa.Column("mvp_character_id", sa.String(36), nullable=True),
        sa.Column("mvp_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.script_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "player_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("character_id", sa.String(36), nullable=False),
        sa.Column("suspicion_reasons", sa.JSON(), nullable=False),
        sa.Column("suspected_by", sa.JSON(), nullable=False),
        sa.Column("player_perspectives", sa.JSON(), nullable=False),
        sa.Column("suspicion", sa.JSON(), nullable=False),
        sa.Column("suspected_intensity", sa.Float(), nullable=False),
        sa.Column("wait_rounds", sa.Integer(), nullable=False),
        sa.Column("total_speeches", sa.Integer(), nullable=False),
        sa.Column("total_words", sa.Integer(), nullable=False),
        sa.Column("remaining_speech_count", sa.Integer(), nullable=False),
        sa.Column("has_spoken_this_round", sa.Boolean(), nullable=False),
        sa.Column("speeches_this_round", sa.Integer(), nullable=False),
        sa.Column("has_voted", sa.Boolean(), nullable=False),
        sa.Column("voted_for", sa.String(36), nullable=True),
        sa.Column("vote_reasoning", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_speech_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.session_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "game_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("record_type", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=True),
        sa.Column("round_num", sa.Integer(), nullable=False),
        sa.Column("speaker_character_id", sa.String(36), nullable=True),
        sa.Column("speaker_name", sa.String(50), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=True),
        sa.Column("summary_content", sa.Text(), nullable=True),
        sa.Column("extra_data", sa.String(500), nullable=True),
        sa.Column("audio_url", sa.String(500), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["game_sessions.session_id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("game_records")
    op.drop_table("player_states")
    op.drop_table("game_sessions")
    op.drop_table("characters")
    op.drop_table("scripts")
