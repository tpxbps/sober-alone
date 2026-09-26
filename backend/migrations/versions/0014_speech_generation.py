"""Persist bounded role generation and explicit player recovery."""

import sqlalchemy as sa
from alembic import op

revision = "0014_speech_generation"
down_revision = "0013_clue_presentation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("game_sessions", sa.Column("speech_generation", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("game_sessions", "speech_generation")
