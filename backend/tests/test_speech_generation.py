import asyncio
import json
from contextlib import aclosing

import pytest
from sqlalchemy import func, select
from test_state_reliability import game as base_game

from app.agents.speech_attempt import SpeechAttempt, current_speech_attempt
from app.db.models import GameRecord, PlayerState
from app.services import speech_generation as limits
from app.services.game_speech import GameSpeechService

game = base_game


@pytest.fixture(autouse=True)
def fast_deadlines(monkeypatch):
    monkeypatch.setattr(limits, "FIRST_VISIBLE_SECONDS", 0.04)
    monkeypatch.setattr(limits, "VISIBLE_IDLE_SECONDS", 0.04)
    monkeypatch.setattr(limits, "GENERATION_SECONDS", 3)
    monkeypatch.setattr(limits, "HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(limits.random, "uniform", lambda *_: 0)


async def service_for(game, generator):
    db, controller = game
    controller.session.current_speaker = "a"
    await db.commit()
    controller.generate_ai_speech = generator

    async def ensure(_id, _db):
        from app.db.models import GameSession

        controller.session = await _db.get(GameSession, "g")
        return controller

    return GameSpeechService(db, ensure)


async def collect(service, **kwargs):
    return [
        json.loads(frame.removeprefix("data: "))
        async for frame in service.stream_ai("g", "a", **kwargs)
    ]


async def speech_count(db):
    return await db.scalar(
        select(func.count()).select_from(GameRecord).where(GameRecord.record_type == "speech")
    )


@pytest.mark.asyncio
async def test_visible_success_commits_once_and_terminal_order(game):
    async def generate(*_):
        current_speech_attempt().thread_id = "accepted-attempt"
        yield {"type": "token", "text": "结论"}

    service = await service_for(game, generate)
    events = await collect(service)
    assert [event["type"] for event in events][-2:] == ["speech_done", "done"]
    db, controller = game
    assert await speech_count(db) == 1
    assert controller.session.speech_generation["status"] == "completed"
    assert controller.session.player_threads["a"] == "accepted-attempt"
    player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "a"))
    assert player.remaining_speech_count == 3


@pytest.mark.asyncio
async def test_empty_frames_retry_once_failure_survives_refresh_and_skip_once(game):
    attempts = []

    async def generate(*_):
        attempts.append(current_speech_attempt())
        while True:
            yield {"type": "token", "text": ""}
            yield {"type": "progress", "status": "分析中"}
            await asyncio.sleep(0.002)

    service = await service_for(game, generate)
    events = await collect(service)
    db, controller = game
    state = controller.session.speech_generation
    assert len(attempts) == 2 and not any(a.active for a in attempts)
    assert state["status"] == "failed" and state["reason"] == "first_visible_timeout"
    assert any(event["type"] == "heartbeat" for event in events)
    assert await speech_count(db) == 0
    player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "a"))
    assert player.remaining_speech_count == 4
    assert limits.public_generation(controller.session)["status"] == "failed"
    await collect(service)
    assert len(attempts) == 2  # a refreshed client must not restart the cycle
    result = await service.skip_ai("g", state["generation_id"])
    assert result["success"]
    assert not (await service.skip_ai("g", state["generation_id"]))["success"]
    await db.refresh(player)
    assert player.remaining_speech_count == 3
    assert await speech_count(db) == 0
    assert await db.scalar(select(func.count()).select_from(GameRecord)) == 1


@pytest.mark.asyncio
async def test_partial_output_stalls_without_replay_or_memory_commit(game):
    attempts = []

    async def generate(*_):
        attempt = current_speech_attempt()
        attempts.append(attempt)
        attempt.role_updates.append({"my_suspicion_graph": {"b": {"score": 0.8}}})
        yield {"type": "token", "text": "尚未完成"}
        await asyncio.sleep(10)

    service = await service_for(game, generate)
    await collect(service)
    db, controller = game
    state = controller.session.speech_generation
    assert len(attempts) == 1
    assert state["reason"] == "visible_idle_timeout" and state["partial_content"] == "尚未完成"
    assert await speech_count(db) == 0
    player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "a"))
    assert not player.suspicion_reasons
    with pytest.raises(asyncio.CancelledError):
        await controller.process_speech("a", "晚到结果", db_session=db, speech_attempt=attempts[0])
    assert await speech_count(db) == 0


@pytest.mark.asyncio
async def test_total_budget_includes_tool_wait_and_stale_retry_rejected(game, monkeypatch):
    monkeypatch.setattr(limits, "FIRST_VISIBLE_SECONDS", 1)
    monkeypatch.setattr(limits, "GENERATION_SECONDS", 0.04)

    async def generate(*_):
        yield {"type": "progress", "status": "查询线索"}
        await asyncio.sleep(10)

    service = await service_for(game, generate)
    await collect(service)
    assert game[1].session.speech_generation["reason"] == "generation_timeout"
    result = await collect(service, retry_generation_id="stale")
    assert result[0]["code"] == "stale_speech"


@pytest.mark.asyncio
async def test_disconnect_closes_generation_and_restores_failed_state(game):
    stopped = asyncio.Event()

    async def generate(*_):
        try:
            yield {"type": "token", "text": "部分正文"}
            await asyncio.sleep(10)
        finally:
            stopped.set()

    service = await service_for(game, generate)
    async with aclosing(service.stream_ai("g", "a")) as stream:
        async for frame in stream:
            if json.loads(frame.removeprefix("data: "))["type"] == "token":
                break
    assert stopped.is_set()
    db, controller = game
    await db.refresh(controller.session)
    assert controller.session.speech_generation["status"] == "failed"
    assert controller.session.speech_generation["partial_content"] == "部分正文"
    assert await speech_count(db) == 0


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


@pytest.mark.asyncio
async def test_network_retry_succeeds_without_extra_charge(game):
    import httpx

    calls = 0

    async def generate(*_):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadError("connection lost")
        yield {"type": "token", "text": "恢复后的完整发言"}

    service = await service_for(game, generate)
    await collect(service)
    assert calls == 2
    assert await speech_count(game[0]) == 1
    assert game[1].session.speech_generation["attempt"] == 2


@pytest.mark.asyncio
async def test_account_recovery_does_not_retry(game):
    from app.core.inference import InferenceRecoveryError

    calls = 0

    async def generate(*_):
        nonlocal calls
        calls += 1
        raise InferenceRecoveryError("top_up_balance")
        yield  # pragma: no cover

    service = await service_for(game, generate)
    with pytest.raises(InferenceRecoveryError):
        await collect(service)
    assert calls == 1 and await speech_count(game[0]) == 0
    assert game[1].session.speech_generation["reason"] == "account_recovery"


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
