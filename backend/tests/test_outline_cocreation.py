"""Offline contracts and durable graph/command integration tests."""

import asyncio
import json
from copy import deepcopy

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.schemas.script_editor import StartWorkflowRequest
from app.db.base import Base
from app.db.models import EditorOperation, EditorWorkflow
from app.script_editor import graph as graph_module
from app.script_editor.outline import actions, nodes, runtime
from app.script_editor.outline.contracts import (
    Direction,
    OutlineAction,
    OutlineCheck,
    OutlineConflict,
    OutlineQuestion,
    new_session,
)
from app.script_editor.services import operation_service, workflow_service

FINAL = "# 雾港\n背景 案件 关系 真凶 动机 手法 时间线 结局\n甲 乙 丙 丁\n第一轮 第二轮"
QUESTION = {
    "title": "您来确定剧情走向：",
    "question": "案件的核心冲突是什么？",
    "options": [
        {"id": "revenge", "label": "旧案复仇", "impact": "将人物关系串联到旧案"},
        {"id": "secret", "label": "共同秘密", "impact": "让所有人共同隐瞒真相"},
    ],
    "recommended_option_id": "revenge",
}


def evidence():
    return OutlineCheck(
        characters=[{"name": name, "quote": name} for name in "甲乙丙丁"],
        clue_rounds=[{"name": name, "quote": name} for name in ("第一轮", "第二轮")],
        ending_mode="single",
        coverage=dict.fromkeys(nodes.REQUIRED_COVERAGE, "背景"),
        issues=[],
    )


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    for module in (actions, runtime, operation_service):
        monkeypatch.setattr(module, "AsyncSessionLocal", factory)
    calls = []
    blocker = {"event": None, "fail": False, "checks_fail": False}

    async def stream(state, session, task, segment_id, status):
        calls.append((status, nodes.context(state, session)))
        current = runtime.current_runtime.get()
        if current:
            await current.begin(session, status, segment_id)
            await current.token("未完成草稿")
        if blocker["event"]:
            await blocker["event"].wait()
        if blocker["fail"]:
            blocker["fail"] = False
            raise ValueError("测试中的模型暂时失败")
        return (
            FINAL
            if status == "finalizing"
            else f"第{len(session['segments']) + 1}段：雾港出现案件。"
        )

    async def structured(schema, system, content):
        if schema is OutlineCheck:
            result = evidence()
            if blocker["checks_fail"]:
                result.issues = ["动机与用户要求冲突"]
            return result
        data = json.JSONDecoder().raw_decode(content)[0]
        if len(data["已确认决策"]) >= 2 or "允许提问：False" in content:
            return Direction(action="finalize")
        return Direction(
            action="ask", next_task="根据刚确认的方向继续推进人物关系", question=QUESTION
        )

    monkeypatch.setattr(nodes, "stream_text", stream)
    monkeypatch.setattr(nodes, "structured", structured)
    runner = operation_service.EditorOperationRunner()
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "checkpoints.db")) as saver:
        await saver.setup()
        graph = graph_module.build_script_gen_graph(saver)
        monkeypatch.setattr(workflow_service, "get_script_gen_graph", lambda: graph)
        yield runner, factory, graph, calls, blocker
        await runner.shutdown()
    runtime.live_runtimes.clear()
    await engine.dispose()


async def settle(runner):
    tasks = list(runner._tasks.values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 5)


async def start(env):
    runner = env[0]
    accepted = await runner.queue_start(StartWorkflowRequest(user_idea="雾港旧案"), "owner")
    await settle(runner)
    service = workflow_service.ScriptEditorWorkflowService()
    state = await service.get_state(accepted["thread_id"])
    return accepted["thread_id"], state


def command(action, state, **kwargs):
    import uuid

    return OutlineAction(
        action=action,
        request_id=str(uuid.uuid4()),
        expected_revision=state["state"]["outline_session"]["revision"],
        **kwargs,
    )


@pytest.mark.asyncio
async def test_question_contract_title_recommendation_and_validation():
    assert OutlineQuestion.model_validate(QUESTION).title == "您来确定剧情走向："
    with pytest.raises(ValidationError):
        OutlineQuestion.model_validate({**QUESTION, "title": ""})
    with pytest.raises(ValidationError):
        OutlineQuestion.model_validate({**QUESTION, "recommended_option_id": "missing"})
    with pytest.raises(ValidationError):
        Direction(action="ask", next_task="继续")


@pytest.mark.asyncio
async def test_multiturn_answers_do_not_replay_opening_and_stop_at_review(env):
    runner, _, _, calls, _ = env
    thread, state = await start(env)
    assert state["interrupt"]["step"] == "outline_wait"
    assert len(calls) == 1
    first = state["state"]["outline_session"]["pending_question"]
    await actions.queue_action(
        runner,
        thread,
        command("answer", state, question_id=first["id"], other_text="凶手希望揭露旧案"),
        "owner",
    )
    await settle(runner)
    state = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    second = state["state"]["outline_session"]["pending_question"]
    assert second["id"] != first["id"]
    assert len(calls) == 2
    await actions.queue_action(
        runner,
        thread,
        command(
            "answer",
            state,
            question_id=second["id"],
            option_id="secret",
            other_text="但保留一名不知情者",
        ),
        "owner",
    )
    await settle(runner)
    state = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    assert state["current_step"] == "review_outline"
    assert not state["is_complete"]
    assert state["state"]["outline_session"]["check"]["passed"]
    assert state["state"]["outline"] == FINAL
    assert state["state"]["first_draft"] == ""
    assert len([c for c in calls if c[0] == "writing"]) == 3


@pytest.mark.asyncio
async def test_duplicate_request_and_stale_question_do_not_consume_next_question(env):
    runner = env[0]
    thread, state = await start(env)
    question = state["state"]["outline_session"]["pending_question"]
    request = command("answer", state, question_id=question["id"], option_id="revenge")
    one = await actions.queue_action(runner, thread, request, "owner")
    await settle(runner)
    two = await actions.queue_action(runner, thread, request, "owner")
    assert one["operation_id"] == two["operation_id"]
    with pytest.raises(OutlineConflict):
        await actions.queue_action(
            runner,
            thread,
            command("answer", state, question_id=question["id"], option_id="secret"),
            "owner",
        )
    # A crash after graph advancement but before operation completion must not replay the answer.
    async with env[1]() as db:
        operation = await db.get(EditorOperation, request.request_id)
        operation.status = "running"
        await db.commit()
    await runner.recover_pending()
    await settle(runner)
    live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    assert len(live["state"]["outline_session"]["decisions"]) == 1
    assert live["state"]["outline_session"]["pending_question"]["id"] != question["id"]


@pytest.mark.asyncio
async def test_stop_questions_survives_rewrite_and_archives_old_version(env):
    runner, _, graph, calls, _ = env
    thread, state = await start(env)
    question = state["state"]["outline_session"]["pending_question"]
    await actions.queue_action(runner, thread, command("stop_questions", state), "owner")
    await settle(runner)
    live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    assert live["current_step"] == "review_outline"
    assert live["state"]["outline_session"]["decisions"][0]["source"] == "ai"
    await actions.queue_action(
        runner,
        thread,
        command("rewrite", live, question_id=question["id"], other_text="改为利益争夺"),
        "owner",
    )
    await settle(runner)
    live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    session = live["state"]["outline_session"]
    assert session["revision"] == 2
    assert session["questions_stopped"] is True
    assert session["decisions"][0]["other_text"] == "改为利益争夺"
    assert session["decisions"][0]["source"] == "user"
    history = [cp async for cp in graph.aget_state_history({"configurable": {"thread_id": thread}})]
    assert {cp.values.get("outline_session", {}).get("revision") for cp in history} >= {1, 2}
    assert "旧案复仇" not in calls[-1][1]


@pytest.mark.asyncio
async def test_pause_cancels_call_and_resume_replaces_unfinished_segment(env):
    runner, factory, _, calls, blocker = env
    thread, state = await start(env)
    question = state["state"]["outline_session"]["pending_question"]
    blocker["event"] = asyncio.Event()
    await actions.queue_action(
        runner,
        thread,
        command("answer", state, question_id=question["id"], option_id="secret"),
        "owner",
    )
    for _ in range(100):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    await actions.queue_action(runner, thread, command("pause", state), "owner")
    async with factory() as db:
        workflow = await db.get(EditorWorkflow, thread)
        assert workflow.outline_control["paused"]
    projected = await runtime.projection(thread)
    assert projected["live"]["text"] == "未完成草稿"
    blocker["event"] = None
    await actions.queue_action(runner, thread, command("continue", state), "owner")
    await settle(runner)
    live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    assert len(live["state"]["outline_session"]["segments"]) == 2
    assert len(live["state"]["outline_session"]["decisions"]) == 1


@pytest.mark.asyncio
async def test_text_failure_retries_only_failed_segment(env):
    runner, _, _, calls, blocker = env
    thread, state = await start(env)
    blocker["fail"] = True
    question = state["state"]["outline_session"]["pending_question"]
    await actions.queue_action(
        runner,
        thread,
        command("answer", state, question_id=question["id"], option_id="secret"),
        "owner",
    )
    await settle(runner)
    await actions.queue_action(runner, thread, command("retry", state), "owner")
    await settle(runner)
    live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    assert len(live["state"]["outline_session"]["segments"]) == 2
    assert len(live["state"]["outline_session"]["decisions"]) == 1
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_quality_repair_is_bounded_and_reports_remaining_issues(env):
    runner, _, _, calls, blocker = env
    thread, state = await start(env)
    blocker["checks_fail"] = True
    await actions.queue_action(runner, thread, command("stop_questions", state), "owner")
    await settle(runner)
    live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    session = live["state"]["outline_session"]
    assert session["status"] == "needs_revision"
    assert session["repairs"] == 2
    assert not session["check"]["passed"]
    assert len([c for c in calls if c[0] == "finalizing"]) == 3


def test_context_omits_chat_discarded_branches_and_unselected_options():
    session = new_session()
    session["decisions"] = [
        {"source": "user", "choice": "旧案", "other_text": "保留悬疑", "question": QUESTION}
    ]
    state = {
        "outline_session": session,
        "user_idea": "案件",
        "outline": "有效正文",
        "chat": "聊天污染",
        "discarded": "废弃正文",
    }
    content = nodes.context(state, session)
    assert "聊天污染" not in content and "废弃正文" not in content
    assert "共同秘密" not in content and "有效正文" in content


def test_evidence_counts_and_quotes_cannot_pass_with_missing_content():
    result = evidence()
    assert nodes.check_issues(result, {"outline": FINAL}) == []
    result.characters[0].quote = "不存在的证据"
    issues = nodes.check_issues(
        result, {"outline": FINAL, "player_count": 5, "ending_mode": "multiple"}
    )
    assert len(issues) == 3


@pytest.mark.asyncio
async def test_stream_subscription_is_authorized_before_first_checkpoint(env, monkeypatch):
    from app.api.routes.script_editor_routes.assets import progress_stream

    runner = env[0]
    monkeypatch.setattr(runner, "_schedule", lambda _: None)
    accepted = await runner.queue_start(StartWorkflowRequest(user_idea="尚未开始调用"), "owner")
    response = await progress_stream(accepted["thread_id"], "owner")
    assert "connected" in await anext(response.body_iterator)
    await response.body_iterator.aclose()


@pytest.mark.asyncio
async def test_pause_before_first_checkpoint_can_resume(env, monkeypatch):
    runner = env[0]
    schedule = runner._schedule
    monkeypatch.setattr(runner, "_schedule", lambda _: None)
    accepted = await runner.queue_start(StartWorkflowRequest(user_idea="开始前暂停"), "owner")
    import uuid

    thread = accepted["thread_id"]
    await actions.queue_action(
        runner,
        thread,
        OutlineAction(action="pause", expected_revision=1, request_id=str(uuid.uuid4())),
        "owner",
    )
    monkeypatch.setattr(runner, "_schedule", schedule)
    await actions.queue_action(
        runner,
        thread,
        OutlineAction(action="continue", expected_revision=1, request_id=str(uuid.uuid4())),
        "owner",
    )
    await settle(runner)
    result = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
    assert result["interrupt"]["step"] == "outline_wait"


def test_explicit_option_recommendation_is_normalized_without_guessing():
    raw = deepcopy(QUESTION)
    raw.pop("recommended_option_id")
    raw["options"][0]["recommended"] = True
    raw["options"][1]["recommended"] = False
    assert OutlineQuestion.model_validate(raw).recommended_option_id == "revenge"
    raw["options"][1]["recommended"] = True
    with pytest.raises(ValidationError):
        OutlineQuestion.model_validate(raw)


@pytest.mark.asyncio
async def test_question_and_automatic_segment_limits_are_enforced(monkeypatch):
    async def always_ask(*_):
        return Direction(action="ask", next_task="继续推进", question=QUESTION)

    monkeypatch.setattr(nodes, "structured", always_ask)
    session = new_session()
    session["questions_asked"] = 5
    result = await nodes.direct_outline({"outline_session": session})
    assert result["outline_session"]["pending_question"] is None
    assert result["outline_session"]["next_action"] == "write"
    session["automatic_segments"] = 4
    result = await nodes.direct_outline({"outline_session": session})
    assert result["outline_session"]["next_action"] == "finalize"


def test_evidence_accepts_markdown_formatting_but_not_invented_quotes():
    check = evidence()
    state = {
        "outline": FINAL.replace("背景", "**背景**"),
        "player_count": 4,
        "num_clue_rounds": 2,
        "ending_mode": "single",
    }
    assert nodes.check_issues(check, state) == []
    check.coverage["background"] = "完全不存在的背景"
    assert any("background" in issue for issue in nodes.check_issues(check, state))


@pytest.mark.asyncio
async def test_structured_question_repairs_once_then_reports_error(monkeypatch):
    calls = []

    class BrokenModel:
        def with_structured_output(self, schema, **kwargs):
            return self

        async def ainvoke(self, messages):
            calls.append(messages[:])
            return {
                "action": "ask",
                "next_task": "续写",
                "question": {"question": "缺少标题和选项"},
            }

    monkeypatch.setattr(nodes, "llm", lambda _: BrokenModel())
    with pytest.raises(ValueError, match="结构化结果仍不完整"):
        await nodes.structured(Direction, "独立协议", "有效正文")
    assert len(calls) == 2
    assert "上一结果未通过格式校验" in calls[1][-1].content


@pytest.mark.asyncio
async def test_new_runner_recovers_uncommitted_segment_without_duplicate_answer(env):
    runner, factory, _, calls, blocker = env
    thread, state = await start(env)
    q = state["state"]["outline_session"]["pending_question"]
    blocker["event"] = asyncio.Event()
    request = command("answer", state, question_id=q["id"], other_text="守护秘密")
    await actions.queue_action(runner, thread, request, "owner")
    for _ in range(100):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    await runner.shutdown()
    async with factory() as db:
        operation = await db.get(EditorOperation, request.request_id)
        assert operation.status == "running"
    blocker["event"] = None
    restarted = operation_service.EditorOperationRunner()
    try:
        await restarted.recover_pending()
        await settle(restarted)
        live = await workflow_service.ScriptEditorWorkflowService().get_state(thread)
        session = live["state"]["outline_session"]
        assert len(session["segments"]) == 2
        assert len(session["decisions"]) == 1
        assert session["decisions"][0]["other_text"] == "守护秘密"
        assert session["consumed_requests"].count(request.request_id) == 1
    finally:
        await restarted.shutdown()


@pytest.mark.asyncio
async def test_phase_restore_gets_fresh_version_and_keeps_stop_control(env):
    runner, _, graph, _, _ = env
    thread, state = await start(env)
    await actions.queue_action(runner, thread, command("stop_questions", state), "owner")
    await settle(runner)
    service = workflow_service.ScriptEditorWorkflowService()
    review = await service.get_state(thread)
    restored = await actions.sync_review_fork(service, thread, review)
    assert restored["current_step"] == "review_outline"
    assert restored["state"]["outline_session"]["revision"] == 2
    projected = await runtime.projection(thread)
    assert projected["revision"] == 2
    assert projected["control"]["questions_stopped"]
    assert not projected["control"]["paused"]
    assert not restored["state"]["first_draft"]
