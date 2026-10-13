"""Record author permission for maintainer script improvements."""

import sqlalchemy as sa
from alembic import op

revision = "0016_optimization_authorization"
down_revision = "0015_game_turns"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scripts",
        sa.Column(
            "optimization_authorized", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )


def downgrade():
    op.drop_column("scripts", "optimization_authorized")
