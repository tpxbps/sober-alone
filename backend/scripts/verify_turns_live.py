"""Explicit paid HTTP turn/reconnect acceptance with isolated sample data.

Run from backend: uv run python -m scripts.verify_turns_live --output <new-directory>
Never collected by CI. Prints timings and identities, not prompts, text or credentials.
"""

import argparse
import asyncio
import json
import logging
import os
import socket
import time
import uuid
from pathlib import Path


async def run(output: Path, model: str):
    output.mkdir(parents=True, exist_ok=True)
    database = output / "game.db"
    if database.exists():
        raise ValueError("Use a fresh output directory")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{database.as_posix()}"
    os.environ["ZHIPUAI_API_KEY"] = ""  # The sample needs no embeddings.
    from app.core import config

    config.LOCAL_DATA_DIR = output
    import httpx
    import uvicorn
    from sqlalchemy import func, select

    from app.db.base import Base
    from app.db.models import GameRecord, PlayerState
    from app.db.session import AsyncSessionLocal, engine
    from app.main import app
    from app.seed import CHARACTERS, SAMPLE_SCRIPT_ID, seed_sample_if_empty
    from app.services.game_turns import game_turn_runner

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await seed_sample_if_empty(db)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    results = []

    async def frames(response):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                yield json.loads(line[6:])

    try:
        while not server.started:
            if task.done():
                await task
            await asyncio.sleep(0.02)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=300) as client:
            human = CHARACTERS[1]["character_id"]
            created = (
                await client.post(
                    "/api/v1/game/create",
                    json={
                        "script_id": SAMPLE_SCRIPT_ID,
                        "human_character_id": human,
                        "llm_configs": {
                            c["character_id"]: {"model": model}
                            for c in CHARACTERS
                            if c["character_id"] != human
                        },
                    },
                )
            ).json()
            assert created["success"]
            session_id = created["session_id"]
            base = f"/api/v1/game/{session_id}"
            for _ in range(3):
                state = (await client.get(base + "/state")).json()
                speaker = state["current_speaker_id"]
                assert speaker
                is_human = speaker == human
                command = {
                    "request_id": str(uuid.uuid4()),
                    "expected_revision": state["state_revision"],
                }
                if is_human:
                    command["content"] = (
                        "我是陆鸣，今晚在广播站准备最后一期直播。请大家先说明各自的时间线。"
                    )
                path = base + ("/speech" if is_human else f"/ai-speech/{speaker}")
                started = time.monotonic()
                seen = set()
                first = None
                final = None
                last_seq = -1
                async with client.stream("POST", path, json=command) as response:
                    async for event in frames(response):
                        turn = event.get("turn", {})
                        assert turn.get("status") not in ("failed", "blocked", "cancelled")
                        last_seq = turn.get("seq", last_seq)
                        if turn.get("content"):
                            seen.add(turn["content"])
                            first = first or round(time.monotonic() - started, 3)
                            # Cancel just the HTTP subscription at a visible token.
                            break
                recovered = (await client.get(base + "/state")).json()
                assert recovered["active_turn"]["turn_id"] == command["request_id"]
                async with client.stream(
                    "GET", base + f"/turns/{command['request_id']}/events?after_seq={last_seq}"
                ) as response:
                    async for event in frames(response):
                        turn = event.get("turn", {})
                        assert turn.get("status") not in ("failed", "blocked", "cancelled")
                        if turn.get("content"):
                            seen.add(turn["content"])
                        if event["type"] == "done":
                            final = event
                            break
                assert final and final["record"]["turn_id"] == command["request_id"]
                assert final["state"]["active_turn"] is None
                if not is_human:
                    assert len(seen) > 1, "Provider output was not incrementally delivered"
                # A response-lost duplicate must return the same finished operation.
                async with client.stream("POST", path, json=command) as response:
                    duplicate = await anext(frames(response))
                    assert (
                        duplicate["type"] == "done"
                        and duplicate["record"]["id"] == final["record"]["id"]
                    )
                async with AsyncSessionLocal() as db:
                    count = await db.scalar(
                        select(func.count())
                        .select_from(GameRecord)
                        .where(GameRecord.turn_id == command["request_id"])
                    )
                    player = await db.scalar(
                        select(PlayerState).where(
                            PlayerState.session_id == session_id,
                            PlayerState.character_id == speaker,
                        )
                    )
                    assert count == 1 and player.total_speeches == 1
                results.append(
                    {
                        "turn_id": command["request_id"],
                        "kind": "human" if is_human else "ai",
                        "first_text_seconds": first,
                        "total_seconds": round(time.monotonic() - started, 3),
                        "distinct_text_snapshots": len(seen),
                        "chars": len(final["record"]["content"]),
                        "record_id": final["record"]["id"],
                    }
                )
                print(json.dumps(results[-1]), flush=True)
                (output / "result.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
                await asyncio.sleep(0.1)
                assert not game_turn_runner.tasks, "Offline client must not launch the next turn"
            await client.post(base + "/end")
            print(
                "PASS durable HTTP turns, detached execution, incremental reconnect, idempotent commits",
                flush=True,
            )
    finally:
        server.should_exit = True
        await task
        listener.close()
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="deepseek-flash")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    logging.getLogger("app.services.game_turns").setLevel(logging.INFO)
    try:
        asyncio.run(run(args.output.resolve(), args.model))
    except Exception as error:
        raise SystemExit(f"FAIL {type(error).__name__}") from None
