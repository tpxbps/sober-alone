import asyncio
import hashlib
import secrets

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.routes.feedback import router
from app.db.base import Base
from app.db.models import GameRecord, GameSession, Script, ScriptFeedback
from app.db.session import get_db
from app.services.script_feedback import FEEDBACK_COOKIE, feedback_summary


@pytest.mark.parametrize(
    "total,positive,label",
    [
        (0, 0, "待评价"),
        (4, 4, "待评价"),
        (5, 4, "好评"),
        (10, 7, "多半好评"),
        (10, 4, "褒贬不一"),
        (10, 2, "多半差评"),
        (10, 1, "差评"),
        (20, 16, "特别好评"),
        (20, 3, "一片差评"),
        (100, 95, "好评如潮"),
        (100, 5, "差评如潮"),
    ],
)
def test_thresholds(total, positive, label):
    assert feedback_summary(total, positive)["label"] == label


@pytest.mark.asyncio
async def test_feedback_session_eligibility_privacy_upsert_and_retention(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'feedback.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    async with factory() as db:
        db.add(Script(script_id="s", title="剧本"))
        await db.flush()
        db.add(
            GameSession(
                session_id="g", script_id="s", human_character_id="human", reviewer_hash=digest
            )
        )
        db.add(GameSession(session_id="legacy", script_id="s", human_character_id="human"))
        await db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/game")

    async def database():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {"recommended": True, "comment": "含剧透的私人意见"}
        assert (await client.put("/game/g/feedback", json=body)).status_code == 403
        client.cookies.set(FEEDBACK_COOKIE, raw)
        assert (await client.put("/game/legacy/feedback", json=body)).status_code == 403
        assert (await client.put("/game/g/feedback", json=body)).status_code == 409
        async with factory() as db:
            session = await db.get(GameSession, "g")
            session.current_stage = "review"
            session.votes = {"human": {"suspect_id": "ai"}}
            await db.commit()
        # Stage alone is not proof that the reveal was persisted.
        assert (await client.put("/game/g/feedback", json=body)).status_code == 409
        async with factory() as db:
            db.add(
                GameRecord(
                    session_id="g", record_type="system", stage="review", raw_content="真相揭晓"
                )
            )
            await db.commit()
        assert (await client.put("/game/g/feedback", json=body)).status_code == 200
        assert (await client.put("/game/g/feedback", json=body)).status_code == 200
        updated = await client.put("/game/g/feedback", json={"recommended": False})
        assert updated.json()["feedback"]["comment"] == body["comment"]
        assert updated.json()["feedback"]["recommended"] is False
        assert (
            await client.put("/game/g/feedback", json={"recommended": True, "comment": "x" * 1001})
        ).status_code == 422
        async with factory() as db:
            db.add(
                GameSession(
                    session_id="replay",
                    script_id="s",
                    human_character_id="human",
                    reviewer_hash=digest,
                    current_stage="review",
                    votes={"human": {"suspect_id": "ai"}},
                )
            )
            await db.flush()
            db.add(
                GameRecord(
                    session_id="replay",
                    record_type="system",
                    stage="review",
                    raw_content="再次揭晓",
                )
            )
            await db.commit()
        responses = await asyncio.gather(
            *(client.put("/game/replay/feedback", json={"recommended": True}) for _ in range(3))
        )
        assert all(r.status_code == 200 for r in responses)
        assert all(r.json()["feedback"]["comment"] == body["comment"] for r in responses)
        async with factory() as db:
            saved = await db.scalar(select(ScriptFeedback))
            assert saved.source_session_id == "replay"
        client.cookies.clear()
        assert (await client.get("/game/g/feedback")).status_code == 403
    async with factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScriptFeedback)) == 1
        await db.execute(delete(GameSession).where(GameSession.session_id == "g"))
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ScriptFeedback)) == 1
        await db.execute(delete(Script).where(Script.script_id == "s"))
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(ScriptFeedback)) == 0
    await engine.dispose()
