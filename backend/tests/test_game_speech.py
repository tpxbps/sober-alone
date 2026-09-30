import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.db.models import GameRecord, GameSession, GameTurn, PlayerState
from app.services.game_service import GameService
from app.services.game_speech import encode_sse
from app.services.game_turns import TurnConflict


async def until(runner, turn_id, predicate):
    async with asyncio.timeout(8):
        while True:
            turn, record = await runner.snapshot("game", turn_id)
            if predicate(turn):
                return turn, record
            await asyncio.sleep(0.01)


def test_encode_sse_preserves_unicode_and_wire_terminator():
    assert (
        encode_sse({"type": "token", "text": "雾港"})
        == 'data: {"type": "token", "text": "雾港"}\n\n'
    )


@pytest.mark.asyncio
async def test_disconnect_keeps_generation_and_reactions_running(turns):
    runner = turns.runner
    await runner.start("game", "ai", "ai", request_id="one", expected_revision=0)
    first, _ = await until(runner, "one", lambda t: bool(t["content"]))
    assert first["content"] == "第一句。"
    subscriber = runner.events("game", "one")
    frame = json.loads((await anext(subscriber)).removeprefix("data: "))
    assert frame["turn"]["content"] == first["content"]
    await subscriber.aclose()
    assert not runner.tasks["one"].done()
    turns.text_gate.set()
    reacting, record = await until(runner, "one", lambda t: t["status"] == "reacting")
    assert record["content"] == "第一句。第二句。"
    assert reacting["record_id"] == record["id"]
    async with turns.factory() as db:
        state = await GameService(db).get_game_state("game")
        assert state["active_turn"]["status"] == "reacting"
        assert state["current_speaker_id"] is None and state["turn_processing"]
    turns.reaction_gate.set()
    final, _ = await until(runner, "one", lambda t: t["status"] == "completed")
    frames = [
        json.loads(f.removeprefix("data: "))
        async for f in runner.events("game", "one", first["seq"])
    ]
    assert len(frames) == 1 and frames[0]["type"] == "done"
    assert frames[0]["state"]["current_speaker_id"] == "human"
    assert frames[0]["state"]["state_revision"] == final["state_revision"]
    assert turns.calls == 1


@pytest.mark.asyncio
async def test_duplicate_tabs_and_delayed_commands_cannot_repeat_turn(turns):
    results = await asyncio.gather(
        *(
            turns.runner.start("game", "ai", "ai", request_id=f"tab-{i}", expected_revision=0)
            for i in range(8)
        )
    )
    ids = {turn["turn_id"] for turn in results}
    assert len(ids) == 1
    turn_id = ids.pop()
    turns.text_gate.set()
    turns.reaction_gate.set()
    await until(turns.runner, turn_id, lambda t: t["status"] == "completed")
    duplicate = await turns.runner.start(
        "game", "ai", "ai", request_id=turn_id, expected_revision=0
    )
    assert duplicate["status"] == "completed"
    with pytest.raises(TurnConflict):
        await turns.runner.start("game", "ai", "ai", request_id="stale", expected_revision=0)
    async with turns.factory() as db:
        assert len(list(await db.scalars(select(GameRecord)))) == 1
        player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "ai"))
        assert player.total_speeches == 1
    assert turns.calls == 1


@pytest.mark.asyncio
async def test_failure_preserves_text_and_retry_reuses_input_checkpoint(turns):
    turns.error = RuntimeError("provider could not complete")
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="retry")
    failed, record = await until(turns.runner, "retry", lambda t: t["status"] == "failed")
    assert failed["content"] == "第一句。" and record is None
    async with turns.factory() as db:
        player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "ai"))
        assert player.total_speeches == 0
        assert (await db.get(GameSession, "game")).current_speaker == "ai"
    turns.error = None
    turns.chunks = ["新的", "发言"]
    turns.reaction_gate.set()
    await turns.runner.retry("game", "retry", failed["attempt"])
    complete, record = await until(turns.runner, "retry", lambda t: t["status"] == "completed")
    assert complete["attempt"] == 2 and record["content"] == "新的发言"
    assert turns.checkpoints == ["before-speech", "before-speech"]


@pytest.mark.asyncio
async def test_transport_retries_have_one_bounded_budget(turns):
    turns.error = httpx.ConnectError("temporary provider connection loss")
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="budget")
    failed, _ = await until(turns.runner, "budget", lambda t: t["status"] == "failed")
    assert turns.calls == 3 and failed["attempt"] == 3
    assert failed["content"] == "第一句。"


@pytest.mark.asyncio
async def test_shutdown_after_commit_resumes_only_reactions(turns):
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="restart")
    await until(turns.runner, "restart", lambda t: t["status"] == "reacting")
    await turns.runner.shutdown()
    turns.reaction_gate.set()
    await turns.runner.recover()
    await until(turns.runner, "restart", lambda t: t["status"] == "completed")
    assert turns.calls == 1
    async with turns.factory() as db:
        assert len(list(await db.scalars(select(GameRecord)))) == 1
        player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "ai"))
        assert player.total_speeches == 1


@pytest.mark.asyncio
async def test_restart_during_generation_keeps_draft_for_explicit_retry(turns):
    await turns.runner.start("game", "ai", "ai", request_id="interrupted")
    await until(turns.runner, "interrupted", lambda t: bool(t["content"]))
    await turns.runner.shutdown()
    await turns.runner.recover()
    turn, _ = await turns.runner.snapshot("game", "interrupted")
    assert turn["status"] == "failed" and turn["content"] == "第一句。"
    assert turns.calls == 1


@pytest.mark.asyncio
async def test_human_ack_is_after_commit_and_counted_once(turns):
    async with turns.factory() as db:
        session = await db.get(GameSession, "game")
        session.current_speaker = "human"
        session.speech_queue = ["human", "ai"]
        await db.commit()
    await turns.runner.start("game", None, "human", "我的原话", request_id="human")
    turn, record = await until(turns.runner, "human", lambda t: t["status"] == "reacting")
    assert record["content"] == "我的原话" and turn["record_id"] == record["id"]
    same = await turns.runner.start("game", None, "human", "我的原话", request_id="human")
    assert same["record_id"] == record["id"]
    turns.reaction_gate.set()
    await until(turns.runner, "human", lambda t: t["status"] == "completed")


@pytest.mark.asyncio
async def test_state_reads_do_not_touch_cached_controller(turns, monkeypatch):
    await turns.runner.start("game", "ai", "ai", request_id="snapshot")
    await until(turns.runner, "snapshot", lambda t: bool(t["content"]))

    def unexpected(*_args, **_kwargs):
        raise AssertionError("State reads must not restore or use a mutable controller")

    monkeypatch.setattr("app.services.game_service.ensure_flow_controller", unexpected)
    async with turns.factory() as db:
        state = await GameService(db).get_game_state("game", resume_pending=False)
        assert state["active_turn"]["turn_id"] == "snapshot"
        assert state["current_speaker_id"] == "ai" and not state["turn_processing"]


@pytest.mark.asyncio
async def test_recovery_does_not_invent_failure_for_newly_accepted_turn(turns):
    async with turns.factory() as db:
        db.add(
            GameTurn(
                turn_id="accepted", session_id="game", speaker_id="ai", kind="ai", stage="intro"
            )
        )
        await db.commit()
    await turns.runner.recover("game")
    turn, _ = await turns.runner.snapshot("game", "accepted")
    assert turn["status"] == "queued"


@pytest.mark.asyncio
async def test_abandon_cancels_pending_reactions_and_cannot_be_revived(turns):
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="abandoned")
    await until(turns.runner, "abandoned", lambda t: t["status"] == "reacting")
    await turns.runner.cancel_session("game")
    await turns.runner.recover()
    turn, record = await turns.runner.snapshot("game", "abandoned")
    assert turn["status"] == "cancelled" and record["content"] == "第一句。第二句。"
    async with turns.factory() as db:
        session = await db.get(GameSession, "game")
        assert session.status == "finished" and not session.pending_speech
    with pytest.raises(TurnConflict):
        await turns.runner.retry("game", "abandoned", 1)
    with pytest.raises(TurnConflict):
        await turns.runner.start("game", "ai", "ai", request_id="too-late")


@pytest.mark.asyncio
async def test_legacy_pending_speech_adoption_never_regenerates_or_recounts(turns):
    async with turns.factory() as db:
        controller = await turns.runner.controller("game", db)
        from app.game.turn_state import process_turn

        await process_turn(
            controller, "ai", "旧对局中已提交的发言", db_session=db, defer_reactions=True
        )
    turns.reaction_gate.set()
    await turns.runner.recover()
    async with turns.factory() as db:
        turn = await db.scalar(select(GameTurn))
        turn_id = turn.turn_id
    await until(turns.runner, turn_id, lambda t: t["status"] == "completed")
    assert turns.calls == 0
    async with turns.factory() as db:
        assert len(list(await db.scalars(select(GameRecord)))) == 1
        player = await db.scalar(select(PlayerState).where(PlayerState.character_id == "ai"))
        assert player.total_speeches == 1


@pytest.mark.asyncio
async def test_account_pause_keeps_draft_and_uses_no_automatic_retry_budget(turns):
    from app.core.inference import InferenceRecoveryError

    turns.error = InferenceRecoveryError("top_up_balance")
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="funding")
    turn, record = await until(turns.runner, "funding", lambda t: t["status"] == "blocked")
    assert turn["content"] == "第一句。" and record is None
    assert turns.calls == 1 and turn["attempt"] == 1
    await turns.runner.recover()
    assert turns.calls == 1


@pytest.mark.asyncio
async def test_restart_after_text_done_commits_saved_text_without_regeneration(turns, monkeypatch):
    from app.services import game_turns

    commit = game_turns.process_turn

    async def delayed_commit(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(game_turns, "process_turn", delayed_commit)
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="before-commit")
    await until(turns.runner, "before-commit", lambda t: t["status"] == "committing")
    await turns.runner.shutdown()
    monkeypatch.setattr(game_turns, "process_turn", commit)
    turns.reaction_gate.set()
    await turns.runner.recover()
    _, record = await until(turns.runner, "before-commit", lambda t: t["status"] == "completed")
    assert turns.calls == 1 and record["content"] == "第一句。第二句。"


@pytest.mark.asyncio
async def test_disconnect_during_acceptance_cannot_cancel_worker_handoff(turns, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    original = turns.runner.start

    async def slow_accept(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(turns.runner, "start", slow_accept)
    request = asyncio.create_task(turns.runner.accept("game", "ai", "ai", request_id="handoff"))
    await entered.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    release.set()
    turns.text_gate.set()
    turns.reaction_gate.set()
    async with asyncio.timeout(3):
        while turns.runner.admissions:
            await asyncio.sleep(0.01)
    await until(turns.runner, "handoff", lambda t: t["status"] == "completed")
    assert turns.calls == 1
