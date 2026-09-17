"""Record the provider of each character voice."""

import sqlalchemy as sa
from alembic import op

revision = "0012_voice_provider"
down_revision = "0011_authoring"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "characters",
        sa.Column("voice_provider", sa.String(30), nullable=False, server_default="stepfun"),
    )


def downgrade():
    op.drop_column("characters", "voice_provider")
