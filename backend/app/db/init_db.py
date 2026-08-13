"""Compatibility wrapper for callers that used the old initializer.

Schema ownership belongs to Alembic. New code and users should call
``python -m app.cli init`` directly.
"""

from app.cli import init


def init_db() -> None:
    """Upgrade the schema and idempotently seed the local sample."""
    init()


if __name__ == "__main__":
    init_db()
