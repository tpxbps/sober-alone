"""Persist outline command controls without rewriting existing checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0010_outline"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "editor_workflows",
        sa.Column("outline_control", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("editor_workflows", "outline_control")
