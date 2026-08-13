import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.system import healthz
from app.main import app


@pytest.mark.asyncio
async def test_healthz_checks_local_database_only():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        assert await healthz(session) == {"status": "ok", "database": "ok"}

    await engine.dispose()


def test_public_openapi_has_system_routes_and_no_ownership_endpoint():
    paths = app.openapi()["paths"]

    assert "/healthz" in paths
    assert "/api/v1/system/capabilities" in paths
    assert not any("ownership" in path for path in paths)
