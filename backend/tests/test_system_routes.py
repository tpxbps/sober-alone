import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.system import healthz
from app.db.base import Base
from app.db.readiness import DatabaseNotInitializedError
from app.main import app, lifespan


@pytest.mark.asyncio
async def test_healthz_checks_local_database_only():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await healthz(session)

    assert exc_info.value.status_code == 503
    assert "uv run python -m app.cli init" in exc_info.value.detail
    assert "scripts" in exc_info.value.detail

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        assert await healthz(session) == {"status": "ok", "database": "ok"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_lifespan_fails_fast_until_schema_exists(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr("app.main.engine", engine)

    with pytest.raises(DatabaseNotInitializedError, match="app.cli init"):
        async with lifespan(app):
            pass

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with lifespan(app):
        pass

    await engine.dispose()


def test_public_openapi_has_system_routes_and_no_ownership_endpoint():
    paths = app.openapi()["paths"]

    assert "/healthz" in paths
    assert "/api/v1/system/capabilities" in paths
    assert not any("ownership" in path for path in paths)


def test_script_editor_route_split_preserves_public_paths_and_methods():
    paths = app.openapi()["paths"]
    expected = {
        "/api/v1/script-editor/start": {"post"},
        "/api/v1/script-editor/{thread_id}/state": {"get"},
        "/api/v1/script-editor/{thread_id}/resume": {"post"},
        "/api/v1/script-editor/{thread_id}/prompt/{step}": {"put"},
        "/api/v1/script-editor/{thread_id}/title": {"put"},
        "/api/v1/script-editor/prompts/defaults": {"get"},
        "/api/v1/script-editor/steps/info": {"get"},
        "/api/v1/script-editor/scripts/{script_id}": {"delete"},
        "/api/v1/script-editor/{thread_id}/asset-progress": {"get"},
        "/api/v1/script-editor/{thread_id}/convert-progress": {"get"},
        "/api/v1/script-editor/{thread_id}/retry-asset/{task_id}": {"post"},
        "/api/v1/script-editor/{thread_id}/retry-convert/{task_id}": {"post"},
        "/api/v1/script-editor/{thread_id}/history": {"get"},
        "/api/v1/script-editor/{thread_id}/checkpoint/{checkpoint_id}": {"get"},
        "/api/v1/script-editor/{thread_id}/fork": {"post"},
        "/api/v1/script-editor/chat": {"post"},
        "/api/v1/script-editor/{thread_id}/progress-stream": {"get"},
    }

    actual = {
        path: {method for method in operations if method != "parameters"}
        for path, operations in paths.items()
        if path.startswith("/api/v1/script-editor")
    }
    assert actual == expected
