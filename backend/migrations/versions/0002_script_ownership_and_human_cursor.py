"""Add private script ownership and per-AI human speech cursors.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scripts",
        sa.Column("owner_key_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "player_states",
        sa.Column(
            "last_seen_human_record_id",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("player_states", "last_seen_human_record_id")
    op.drop_column("scripts", "owner_key_hash")
