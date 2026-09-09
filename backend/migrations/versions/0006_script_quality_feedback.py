"""Add content-bound quality metadata and anonymous post-game feedback.

Revision ID: 0006
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scripts", sa.Column("content_fingerprint", sa.String(64), nullable=True))
    op.add_column("scripts", sa.Column("ai_review", sa.JSON(), nullable=True))
    op.add_column("scripts", sa.Column("quality_report", sa.JSON(), nullable=True))
    op.add_column("game_sessions", sa.Column("reviewer_hash", sa.String(64), nullable=True))
    op.create_table(
        "script_feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "script_id",
            sa.String(64),
            sa.ForeignKey("scripts.script_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reviewer_hash", sa.String(64), nullable=False),
        sa.Column("recommended", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_session_id", sa.String(36), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("script_id", "reviewer_hash", name="uq_feedback_reviewer"),
    )
    op.create_index("ix_script_feedback_script_id", "script_feedback", ["script_id"])


def downgrade():
    op.drop_table("script_feedback")
    op.drop_column("game_sessions", "reviewer_hash")
    for name in ("quality_report", "ai_review", "content_fingerprint"):
        op.drop_column("scripts", name)
