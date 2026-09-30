import asyncio

import pytest
from sqlalchemy import func, select
from test_state_reliability import game as base_game

from app.agents.speech_attempt import SpeechAttempt
from app.db.models import GameRecord

game = base_game


async def speech_count(db):
    return await db.scalar(
        select(func.count()).select_from(GameRecord).where(GameRecord.record_type == "speech")
    )


@pytest.mark.asyncio
async def test_previous_attempt_cannot_commit_after_replacement(game):
    db, controller = game
    controller.session.current_speaker = "a"
    controller.session.speech_generation = {
        "generation_id": "new",
        "attempt_id": "new-attempt",
        "status": "generating",
    }
    await db.commit()
    stale = SpeechAttempt("old", "old-attempt")
    result = await controller.process_speech("a", "晚到正文", db_session=db, speech_attempt=stale)
    assert not result["success"] and await speech_count(db) == 0


def test_metrics_never_forward_prompt_or_reply():
    from app.services.speech_telemetry import report_speech_metric, set_speech_observer

    metrics = []
    set_speech_observer(metrics.append)
    try:
        report_speech_metric(
            "attempt_finished",
            "g",
            {"partial_content": "private", "attempt_id": "a"},
            prompt="private",
            reply="private",
            first_visible_ms=100,
        )
    finally:
        set_speech_observer(None)
    assert "private" not in str(metrics)
    assert metrics[0]["first_visible_ms"] == 100


@pytest.mark.asyncio
async def test_real_graph_attempt_history_isolated_until_pointer_is_accepted():
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from test_stage_boundaries import CaptureModel

    from app.agents.agent_player import AgentPlayer
    from app.agents.game_model_paths import build_role_agent
    from app.agents.speech_attempt import speech_attempt_scope

    model, saver = CaptureModel(), InMemorySaver()
    graph = build_role_agent(
        model, model, system_prompt="角色", rag_enabled=False, checkpointer=saver, middleware=[]
    )
    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="已接受的上下文")],
            "current_stage": "intro",
            "public_clues": [],
        },
        {"configurable": {"thread_id": "g_a"}},
    )
    player = object.__new__(AgentPlayer)
    player._agent, player._checkpointer = graph, saver
    player.session_id, player.script_id, player.character_id, player.character_name = (
        "g",
        "s",
        "a",
        "甲",
    )
    player.thread_id = "g_a"

    async def knowledge(_state):
        return ""

    player._build_knowledge_context = knowledge
    for attempt_id, text in [("discarded", "未提交尝试"), ("accepted", "新的有效发言")]:
        attempt = SpeechAttempt("generation", attempt_id)
        with speech_attempt_scope(attempt):
            _ = [
                chunk
                async for chunk in player.speak(
                    {"context": text, "agent_thread_id": "g_a"}, "intro"
                )
            ]
    accepted = await graph.aget_state({"configurable": {"thread_id": "g_a_accepted"}})
    text = str(accepted.values["messages"])
    assert "已接受的上下文" in text and "新的有效发言" in text
    assert "未提交尝试" not in text
    canonical = await graph.aget_state({"configurable": {"thread_id": "g_a"}})
    assert "新的有效发言" not in str(canonical.values["messages"])


@pytest.mark.asyncio
async def test_database_fence_rejects_a_stale_orm_snapshot(game):
    from sqlalchemy import update

    from app.db.models import GameSession

    db, controller = game
    controller.session.current_speaker = "a"
    old = {
        "generation_id": "old",
        "attempt_id": "old-attempt",
        "status": "generating",
        "stage": controller.session.current_stage,
        "round": controller.session.current_round,
    }
    controller.session.speech_generation = old
    await db.commit()
    await db.execute(
        update(GameSession)
        .where(GameSession.session_id == "g")
        .values(speech_generation={**old, "generation_id": "replacement"})
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    assert controller.session.speech_generation["generation_id"] == "old"
    result = await controller.process_speech(
        "a", "晚到的旧结果", db_session=db, speech_attempt=SpeechAttempt("old", "old-attempt")
    )
    assert not result["success"] and await speech_count(db) == 0


@pytest.mark.asyncio
async def test_durable_attempt_accepts_checkpoint_only_after_commit(turns, monkeypatch):
    from test_game_speech import until

    from app.agents.speech_attempt import current_speech_attempt
    from app.db.models import GameSession
    from app.services import game_turns

    attempt_refs = []

    async def generate():
        attempt = current_speech_attempt()
        attempt_refs.append(attempt)
        attempt.thread_id = "accepted-scratch"
        attempt.observation_ids = {"one-observation"}
        yield {"type": "token", "text": "完整正文"}

    turns.generator = generate
    original = game_turns.process_turn

    async def delayed(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(game_turns, "process_turn", delayed)
    await turns.runner.start("game", "ai", "ai", request_id="scratch")
    await until(turns.runner, "scratch", lambda t: t["status"] == "committing")
    async with turns.factory() as db:
        assert not (await db.get(GameSession, "game")).player_threads
    await turns.runner.shutdown()
    assert not attempt_refs[0].active
    monkeypatch.setattr(game_turns, "process_turn", original)
    turns.reaction_gate.set()
    await turns.runner.recover()
    await until(turns.runner, "scratch", lambda t: t["status"] == "completed")
    async with turns.factory() as db:
        assert (await db.get(GameSession, "game")).player_threads["ai"] == "accepted-scratch"
        assert await speech_count(db) == 1
    assert len(attempt_refs) == 1


@pytest.mark.asyncio
async def test_rate_limit_cooldown_retry_is_single_budget(turns, monkeypatch):
    import time

    from test_game_speech import until
    from test_rate_limits import limited

    from app.core import rate_limits

    monkeypatch.setattr(rate_limits.random, "uniform", lambda *_: 0)
    starts = []

    async def generate():
        starts.append(time.monotonic())
        if len(starts) < 3:
            raise limited("0.06")
        yield {"type": "token", "text": "恢复后的正文"}

    turns.generator = generate
    turns.reaction_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="cooldown")
    await until(turns.runner, "cooldown", lambda t: t["status"] == "completed")
    assert len(starts) == 3
    assert all(b - a >= 0.06 for a, b in zip(starts, starts[1:]))
    async with turns.factory() as db:
        assert await speech_count(db) == 1


@pytest.mark.asyncio
async def test_excessive_retry_after_preserves_partial_and_does_not_charge(turns):
    from test_game_speech import until
    from test_rate_limits import limited

    calls = []

    async def generate():
        calls.append(1)
        yield {"type": "token", "text": "未完成正文"}
        raise limited("3600")

    turns.generator = generate
    await turns.runner.start("game", "ai", "ai", request_id="long-cooldown")
    snapshot, _ = await until(turns.runner, "long-cooldown", lambda t: t["status"] == "failed")
    assert snapshot["content"] == "未完成正文" and len(calls) == 1
    async with turns.factory() as db:
        assert await speech_count(db) == 0


@pytest.mark.asyncio
async def test_continuous_empty_output_has_explicit_failure_not_skip(turns, monkeypatch):
    from test_game_speech import until

    from app.services import game_turns

    monkeypatch.setattr(game_turns, "GENERATION_SECONDS", 0.05)

    async def generate():
        while True:
            yield {"type": "token", "text": ""}
            await asyncio.sleep(0.001)

    turns.generator = generate
    await turns.runner.start("game", "ai", "ai", request_id="empty")
    snapshot, _ = await until(turns.runner, "empty", lambda t: t["status"] == "failed")
    assert snapshot["content"] == ""
    async with turns.factory() as db:
        assert await speech_count(db) == 0


@pytest.mark.asyncio
async def test_legacy_generation_failure_is_adopted_without_model_call(turns):
    from app.db.models import GameSession

    async with turns.factory() as db:
        session = await db.get(GameSession, "game")
        session.speech_generation = {
            "generation_id": "legacy",
            "character_id": "ai",
            "status": "failed",
            "partial_content": "旧正文",
        }
        await db.commit()
    await turns.runner.recover()
    snapshot, _ = await turns.runner.snapshot("game", "legacy")
    assert snapshot["status"] == "failed" and snapshot["content"] == "旧正文"
    assert turns.calls == 0
