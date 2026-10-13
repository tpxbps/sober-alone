"""Explicit paid provider smoke checks; never collected by pytest.

Usage:
    uv run python -m scripts.live_api_smoke deepseek
    uv run python -m scripts.live_api_smoke stepfun

The script prints only check names and sizes. It never prints prompts, model
content, audio, database content or API keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Literal

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import DEFAULT_MODELS, settings
from app.core.llm_factory import create_llm, create_summary_llm
from app.db.base import Base
from app.db.models import GameRecord, PlayerState
from app.seed import CHARACTERS, SAMPLE_SCRIPT_ID, seed_sample_if_empty
from app.services.game_service import GameService, remove_flow_controller
from app.services.tts_service import TTSService


class StructuredProbe(BaseModel):
    status: Literal["ok"]
    count: int


@tool
def live_probe(value: int) -> str:
    """Return a stable marker after receiving the requested integer."""
    return f"tool-ok-{value}"


def report(name: str, **metadata: int) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in metadata.items())
    print(f"PASS {name}{' ' + suffix if suffix else ''}")


async def deepseek_smoke() -> None:
    if not settings.DEEPSEEK_API_KEY:
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    model = create_llm(
        model=DEFAULT_MODELS["deepseek"],
        temperature=0,
        timeout=90,
        max_retries=1,
        disable_thinking=True,
    )

    ordinary = await model.ainvoke([HumanMessage(content="只回复 OK")])
    if not str(ordinary.content).strip():
        raise RuntimeError("DeepSeek ordinary response was empty")
    report("deepseek.ordinary", chars=len(str(ordinary.content)))

    structured = model.with_structured_output(
        StructuredProbe, method="function_calling", tool_choice="auto"
    )
    structured_result = await structured.ainvoke(
        [HumanMessage(content="返回 status=ok 和 count=1")]
    )
    if not isinstance(structured_result, StructuredProbe) or structured_result.count != 1:
        raise RuntimeError("DeepSeek structured output failed")
    report("deepseek.structured")

    tool_model = model.bind_tools([live_probe], tool_choice="live_probe")
    tool_message = await tool_model.ainvoke(
        [HumanMessage(content="调用 live_probe，value 必须是 7")]
    )
    calls = getattr(tool_message, "tool_calls", [])
    if not calls or calls[0].get("name") != "live_probe":
        raise RuntimeError("DeepSeek did not produce the required tool call")
    report("deepseek.tool_call", calls=len(calls))

    with tempfile.TemporaryDirectory(prefix="sober-alone-live-") as directory:
        database = Path(directory) / "live.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            await seed_sample_if_empty(session)
            service = GameService(session)
            created = await service.create_game(
                SAMPLE_SCRIPT_ID,
                CHARACTERS[0]["character_id"],
            )
            if not created.get("success"):
                raise RuntimeError(f"Game creation failed: {created.get('error', 'unknown')}")
            session_id = created["session_id"]
            ai_character_id = CHARACTERS[1]["character_id"]
            controller = service.runtime_repository
            del controller  # prove the smoke uses only the public GameService façade below

            from app.services.game_service import get_flow_controller

            flow = get_flow_controller(session_id)
            if flow is None:
                raise RuntimeError("Flow controller was not registered")
            flow.session.speech_queue = [ai_character_id]
            flow.session.current_speaker = ai_character_id

            event_types: list[str] = []
            async for payload in service.process_ai_speech_stream(session_id, ai_character_id):
                event = json.loads(payload.removeprefix("data: ").strip())
                event_types.append(event["type"])
            if "token" not in event_types or event_types[-2:] != ["speech_done", "done"]:
                raise RuntimeError(f"Unexpected SSE event sequence: {event_types}")
            report("deepseek.ai_sse", events=len(event_types))

            record = await session.scalar(
                select(GameRecord).where(
                    GameRecord.session_id == session_id,
                    GameRecord.speaker_character_id == ai_character_id,
                )
            )
            reacted_state = await session.scalar(
                select(PlayerState).where(
                    PlayerState.session_id == session_id,
                    PlayerState.character_id == CHARACTERS[2]["character_id"],
                )
            )
            if record is None or reacted_state is None:
                raise RuntimeError("Speech or reaction target was not persisted")
            persisted = sum(
                bool(value)
                for value in (
                    reacted_state.suspicion_reasons,
                    reacted_state.suspected_by,
                    reacted_state.player_perspectives,
                )
            )
            report("deepseek.reaction_persistence", populated_fields=persisted)
            remove_flow_controller(session_id)
        await engine.dispose()


async def stepfun_smoke() -> None:
    if not settings.STEPFUN_API_KEY:
        raise SystemExit("STEPFUN_API_KEY is not configured")
    summary = await create_summary_llm().ainvoke(
        [HumanMessage(content="把‘雾港的灯亮了’压缩为不超过八个字")]
    )
    if not str(summary.content).strip():
        raise RuntimeError("StepFun summary response was empty")
    report("stepfun.summary", chars=len(str(summary.content)))

    audio = await TTSService.synthesize_on_demand("雾港测试。", "cixingnansheng")
    if not audio or len(audio) < 100:
        raise RuntimeError("StepFun TTS returned no usable audio")
    report("stepfun.tts", bytes=len(audio))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run paid, manual provider smoke checks")
    parser.add_argument("provider", choices=("deepseek", "stepfun"))
    provider = parser.parse_args().provider
    asyncio.run(deepseek_smoke() if provider == "deepseek" else stepfun_smoke())


if __name__ == "__main__":
    main()
