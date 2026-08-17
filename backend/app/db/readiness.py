"""Local database readiness checks shared by startup and health endpoints."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

REQUIRED_TABLES = frozenset(
    {"scripts", "characters", "game_sessions", "player_states", "game_records"}
)
INIT_COMMAND = "uv run python -m app.cli init"


class DatabaseNotInitializedError(RuntimeError):
    """Raised when the local SQLite schema has not been migrated yet."""

    def __init__(self, missing_tables: set[str]) -> None:
        self.missing_tables = frozenset(missing_tables)
        missing = ", ".join(sorted(missing_tables))
        super().__init__(
            "Local database schema is not initialized "
            f"(missing tables: {missing}). From the backend directory, run: {INIT_COMMAND}"
        )


async def ensure_database_ready(db: AsyncConnection | AsyncSession) -> None:
    """Verify that every Alembic-managed business table exists."""

    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
    existing_tables = set(result.scalars())
    missing_tables = set(REQUIRED_TABLES - existing_tables)
    if missing_tables:
        raise DatabaseNotInitializedError(missing_tables)
