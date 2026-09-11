"""Add optional vote-selected epilogues without changing existing scripts.

Revision ID: 0008
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("scripts", sa.Column("ending_config", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("scripts", "ending_config")
