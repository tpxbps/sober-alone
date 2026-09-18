"""Persist the player's acknowledgement of a clue presentation."""

import sqlalchemy as sa
from alembic import op

revision = "0013_clue_presentation"
down_revision = "0012_voice_provider"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("game_sessions", sa.Column("clue_presentation_state", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("game_sessions", "clue_presentation_state")
