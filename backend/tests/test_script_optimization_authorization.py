import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.game import router as game_router
from app.api.routes.script_editor import router as editor_router
from app.db.base import Base
from app.db.models import Script
from app.db.session import get_db
from app.script_editor.ownership import AUTHOR_KEY_HEADER, hash_author_key


@pytest.mark.asyncio
async def test_authorization_defaults_permissions_validation_and_persistence(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'authorization.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    author_key = "test-author-key-00000000000000000000"
    headers = {AUTHOR_KEY_HEADER: author_key}
    async with factory() as db:
        db.add_all(
            [
                Script(
                    script_id="owned",
                    title="作者的剧本",
                    owner_key_hash=hash_author_key(author_key),
                ),
                Script(script_id="unowned", title="无作者的剧本"),
            ]
        )
        await db.commit()

    app = FastAPI()
    app.include_router(game_router)
    app.include_router(editor_router)

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    endpoint = "/script-editor/scripts/owned/optimization-authorization"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            scripts = (await client.get("/game/scripts", headers=headers)).json()["scripts"]
            assert all(script["optimization_authorized"] is True for script in scripts)
            owned = next(script for script in scripts if script["script_id"] == "owned")
            assert owned["can_manage"] is True
            assert "owner_key_hash" not in owned

            body = {"optimization_authorized": False}
            for invalid_headers in (
                {},
                {AUTHOR_KEY_HEADER: "short"},
                {AUTHOR_KEY_HEADER: "other-author-key-0000000000000000000"},
            ):
                assert (
                    await client.put(endpoint, json=body, headers=invalid_headers)
                ).status_code == 403
            assert (
                await client.put(endpoint.replace("owned/", "unowned/"), json=body, headers=headers)
            ).status_code == 403
            assert (
                await client.put(endpoint.replace("owned/", "missing/"), json=body, headers=headers)
            ).status_code == 404
            for invalid_body in (
                {},
                {"optimization_authorized": None},
                {"optimization_authorized": "false"},
                {"optimization_authorized": 0},
            ):
                assert (
                    await client.put(endpoint, json=invalid_body, headers=headers)
                ).status_code == 422

            # Repeated requests are safe, and each list request reads the persisted value.
            for authorized in (False, False, True):
                response = await client.put(
                    endpoint, json={"optimization_authorized": authorized}, headers=headers
                )
                assert response.status_code == 200
                assert response.json() == {
                    "success": True,
                    "script_id": "owned",
                    "optimization_authorized": authorized,
                }
                scripts = (await client.get("/game/scripts", headers=headers)).json()["scripts"]
                owned = next(script for script in scripts if script["script_id"] == "owned")
                assert owned["optimization_authorized"] is authorized
                async with factory() as db:
                    persisted = await db.get(Script, "owned")
                    assert persisted.optimization_authorized is authorized
                    assert persisted.title == "作者的剧本"
    finally:
        await engine.dispose()
