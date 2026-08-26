"""Local database readiness checks shared by startup and health endpoints."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

REQUIRED_TABLES = frozenset(
    {"scripts", "characters", "game_sessions", "player_states", "game_records"}
)
REQUIRED_COLUMNS = {
    "scripts": frozenset({"owner_key_hash"}),
    "player_states": frozenset({"last_seen_human_record_id"}),
}
INIT_COMMAND = "uv run python -m app.cli init"


class DatabaseNotInitializedError(RuntimeError):
    """Raised when the local SQLite schema is missing or behind the code."""

    def __init__(
        self,
        missing_tables: set[str] | None = None,
        missing_columns: set[str] | None = None,
    ) -> None:
        self.missing_tables = frozenset(missing_tables or set())
        self.missing_columns = frozenset(missing_columns or set())
        if self.missing_tables:
            details = f"missing tables: {', '.join(sorted(self.missing_tables))}"
            state = "not initialized"
        else:
            details = f"missing columns: {', '.join(sorted(self.missing_columns))}"
            state = "out of date"
        super().__init__(
            f"Local database schema is {state} ({details}). "
            f"Stop the backend and, from the backend directory, run: {INIT_COMMAND}"
        )


async def ensure_database_ready(db: AsyncConnection | AsyncSession) -> None:
    """Verify that every Alembic-managed business table exists."""

    result = await db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))
    existing_tables = set(result.scalars())
    missing_tables = set(REQUIRED_TABLES - existing_tables)
    if missing_tables:
        raise DatabaseNotInitializedError(missing_tables)

    missing_columns: set[str] = set()
    for table_name, required_columns in REQUIRED_COLUMNS.items():
        columns_result = await db.execute(text(f'PRAGMA table_info("{table_name}")'))
        existing_columns = {row[1] for row in columns_result}
        missing_columns.update(
            f"{table_name}.{column_name}" for column_name in required_columns - existing_columns
        )
    if missing_columns:
        raise DatabaseNotInitializedError(missing_columns=missing_columns)
