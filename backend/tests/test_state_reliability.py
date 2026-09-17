from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.reaction import HumanSpeechReactionPayload, SpeechReactionPayload
from app.agents.role_state import apply_beliefs, observations
from app.db.base import Base
from app.db.models import Character, GameRecord, GameSession, PlayerState, Script
from app.game.flow_controller import GameFlowController
from app.game.turn_state import finish_pending, observation_context

NAMES = {"human": "真人", "a": "甲", "b": "乙"}


@pytest.mark.asyncio
async def test_human_raw_keeps_whitespace_and_citation_spelling(game):
    db, controller = game
    original = "  @甲 原文 `c01`\n第二行。\n"
    await controller.process_speech("human", original, is_human=True, db_session=db)
    record = await db.scalar(select(GameRecord).where(GameRecord.record_type == "speech"))
    assert record.raw_content == original
    for cid in ("a", "b"):
        player = await db.scalar(select(PlayerState).where(PlayerState.character_id == cid))
        assert observations(player.player_perspectives)["human"][0]["text"] == original


@pytest.mark.asyncio
async def test_clue_tool_uses_same_absolute_contract_and_allows_omitted_array(game, monkeypatch):
    from app.agents.context import clear_db_session, set_db_session
    from app.agents.tools import reaction

    db, _ = game
    player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "a"))
    player.suspicion_reasons = {"b": {"score": 0.9, "reason": "旧理由"}}
    await db.commit()
    monkeypatch.setattr(reaction, "get_stream_writer", lambda: lambda *_args: None)
    set_db_session(db)
    try:
        result = await reaction.update_role_reaction.coroutine(
            runtime=SimpleNamespace(
                state={
                    "session_id": "g",
                    "character_id": "a",
                    "current_stage": "clue_analysis",
                    "character_name_map": NAMES,
                }
            ),
            suspicion_changes=[{"target": "乙", "score": 0, "reason": "洗清"}],
        )
    finally:
        clear_db_session()
    assert "最新心理状态" in result
    assert player.suspicion_reasons == {"b": {"score": 0, "reason": "洗清"}}
    assert player.suspicion == {"b": 0}


@pytest.fixture
async def game():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(Script(script_id="s", title="测试", game_full_process=[]))
        db.add_all(
            [Character(script_id="s", character_id=cid, name=name) for cid, name in NAMES.items()]
        )
        session = GameSession(
            session_id="g",
            script_id="s",
            human_character_id="human",
            current_stage="free_discussion",
            current_speaker="human",
            speech_queue=[],
        )
        db.add(session)
        await db.flush()
        db.add_all(
            [
                PlayerState(session_id="g", character_id=cid, remaining_speech_count=4)
                for cid in NAMES
            ]
        )
        await db.commit()

        async def broadcast(**kwargs):
            return {
                cid: {"my_suspicion_graph": {}, "my_suspected_by": {}, "main_perspective": "摘要"}
                for cid in kwargs.get("target_ids", [])
            }

        manager = SimpleNamespace(
            get_character_name=lambda cid: NAMES.get(cid, ""), broadcast_speech=broadcast
        )
        controller = GameFlowController(
            session,
            {"characters": [{"character_id": cid, "name": name} for cid, name in NAMES.items()]},
            manager,
        )
        yield db, controller
    await engine.dispose()


def test_absolute_updates_and_legacy_conflicts_are_canonical():
    player = PlayerState(
        character_id="a",
        suspicion_reasons={"乙": {"score": 0.2}, "b": {"score": 0.9}},
        suspected_by={"真人": {"score": 0.8, "need_response": True}},
    )
    assert player.get_agent_state(NAMES)["my_suspicion_graph"]["乙"]["score"] == 0.9
    apply_beliefs(
        player,
        {
            "my_suspicion_graph": {"乙": {"score": 0.1, "reason": "新证据洗清嫌疑"}},
            "my_suspected_by": {"真人": {"score": 0, "need_response": False}},
        },
        NAMES,
    )
    assert player.suspicion == {"b": 0.1}
    with pytest.raises(ValueError):
        apply_beliefs(
            player, {"my_suspicion_graph": {"乙": {"score": 0.8}, "b": {"score": 0.7}}}, NAMES
        )
    assert player.suspicion_reasons["b"]["reason"] == "新证据洗清嫌疑"
    assert player.suspected_intensity == 0
    assert not player.suspected_by["human"]["need_response"]
    with pytest.raises(ValueError):
        apply_beliefs(
            player, {"my_suspicion_graph": {"乙": {"score": 0.8}, "陌生人": {"score": 0.7}}}, NAMES
        )
    assert player.suspicion == {"b": 0.1}


@pytest.mark.parametrize("score", [1.1, -0.1, float("nan"), float("inf")])
def test_invalid_scores_are_rejected_instead_of_reinterpreted(score):
    with pytest.raises(ValidationError):
        SpeechReactionPayload(suspicion_changes=[{"target": "乙", "score": score}])


def test_human_schema_has_no_summary_and_duplicate_targets_are_rejected():
    assert "main_perspective" not in HumanSpeechReactionPayload.model_json_schema()["properties"]
    with pytest.raises(ValidationError):
        SpeechReactionPayload(suspicion_changes=[{"target": "乙"}, {"target": "乙"}])


@pytest.mark.asyncio
async def test_reactions_read_prior_state_and_scheduler_sees_new_state(game):
    db, controller = game
    player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "a"))
    player.suspicion_reasons = {"b": {"score": 0.8, "reason": "旧理由"}}
    await db.commit()

    async def broadcast(**kwargs):
        assert kwargs["contexts"]["a"]["current_state"]["my_suspicion_graph"]["乙"]["score"] == 0.8
        assert kwargs["contexts"]["a"]["is_human"]
        return {
            "a": {
                "my_suspicion_graph": {"乙": {"score": 0.2}},
                "my_suspected_by": {"真人": {"score": 1, "need_response": True}},
            }
        }

    async def choose(**kwargs):
        state = next(value for value in kwargs["player_states"] if value["character_id"] == "a")
        assert state["suspected_intensity"] == 1
        assert state["suspicion"] == {"b": 0.2}
        return None

    controller.agent_manager.broadcast_speech = broadcast
    controller.scheduler.select_next_speaker = choose
    result = await controller.process_speech(
        "human", "@甲 请回答，原话一字不删。", is_human=True, db_session=db
    )
    assert result["success"]
    context, ids = await observation_context(controller, "a", db)
    assert context.count("@甲 请回答，原话一字不删。") == 1
    assert "直接点名" in context
    assert len(ids) == 1


@pytest.mark.asyncio
async def test_consumption_is_per_ai_and_errors_do_not_consume(game):
    db, controller = game
    await controller.process_speech("human", "完整真人原文", is_human=True, db_session=db)
    _, ids = await observation_context(controller, "a", db)
    controller._pending_observation_ids = {"a": ids}
    await controller.process_speech("a", "错误提示", skip_reactions=True, db_session=db)
    text, ids = await observation_context(controller, "a", db)
    assert "完整真人原文" in text
    controller._pending_observation_ids = {"a": ids}
    await controller.process_speech("a", "有效回答", consume_human_context=True, db_session=db)
    assert "完整真人原文" not in (await observation_context(controller, "a", db))[0]
    assert "完整真人原文" in (await observation_context(controller, "b", db))[0]


@pytest.mark.asyncio
async def test_interrupted_reactions_resume_without_duplicate_records_or_counters(game):
    import asyncio

    db, controller = game

    async def interrupted(**kwargs):
        raise asyncio.CancelledError

    controller.agent_manager.broadcast_speech = interrupted
    with pytest.raises(asyncio.CancelledError):
        await controller.process_speech("human", "已提交原文", is_human=True, db_session=db)
    assert controller.session.pending_speech and controller.session.current_speaker is None

    async def recovered(**kwargs):
        return {}

    controller.agent_manager.broadcast_speech = recovered
    await finish_pending(controller, db)
    await finish_pending(controller, db)
    assert len(list(await db.scalars(select(GameRecord)))) == 1
    human = await db.scalar(select(PlayerState).where(PlayerState.character_id == "human"))
    assert human.total_speeches == 1 and human.remaining_speech_count == 3
    a = await db.scalar(select(PlayerState).where(PlayerState.character_id == "a"))
    assert len(observations(a.player_perspectives)["human"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["reauthorize_api_key", "top_up_balance", "api_key_quota"])
async def test_account_recovery_keeps_reactions_pending_without_spending_attempts(game, action):
    from app.core.inference import InferenceRecoveryError

    db, controller = game

    async def unavailable(**kwargs):
        raise InferenceRecoveryError(action)

    controller.agent_manager.broadcast_speech = unavailable
    with pytest.raises(InferenceRecoveryError):
        await controller.process_speech("human", "已提交发言", is_human=True, db_session=db)
    for _ in range(3):
        with pytest.raises(InferenceRecoveryError):
            await finish_pending(controller, db)
        assert controller.session.pending_speech["attempts"] == {}
        assert controller.session.current_speaker is None

    recovered_targets = []

    async def available(**kwargs):
        recovered_targets.extend(kwargs["target_ids"])
        return {}

    controller.agent_manager.broadcast_speech = available
    await finish_pending(controller, db)
    assert set(recovered_targets) == {"a", "b"}
    assert not controller.session.pending_speech
    assert len(list(await db.scalars(select(GameRecord)))) == 1
    human = await db.scalar(select(PlayerState).where(PlayerState.character_id == "human"))
    assert human.total_speeches == 1 and human.remaining_speech_count == 3


@pytest.mark.asyncio
async def test_paused_controller_read_does_not_resume_pending_inference(game, monkeypatch):
    from app.services import game_service

    db, controller = game
    controller.session.pending_speech = {"record_id": 999, "targets": ["a"]}
    await db.commit()

    class Registry:
        async def get_or_restore(self, *_args):
            return controller

    monkeypatch.setattr(game_service, "_flow_controllers", Registry())
    # The nonexistent record would fail if reading resumed the pending work.
    assert await game_service.ensure_flow_controller("g", db, resume_pending=False) is controller
    assert controller.session.pending_speech["record_id"] == 999


@pytest.mark.asyncio
async def test_reaction_batch_stops_other_inference_on_account_recovery(monkeypatch):
    import asyncio

    from app.agents.agent_manager import AgentManager
    from app.core.inference import InferenceRecoveryError

    manager = AgentManager("recovery-test", "script")
    manager.agents = {cid: SimpleNamespace(agent=object()) for cid in ("a", "b")}
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def reaction(cid, *_args, **_kwargs):
        if cid == "a":
            await entered.wait()
            raise InferenceRecoveryError("reauthorize_api_key")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(manager, "_get_reaction_with_timeout", reaction)
    with pytest.raises(InferenceRecoveryError):
        await asyncio.wait_for(manager.broadcast_speech("human", "一条发言"), timeout=1)
    assert cancelled.is_set()
