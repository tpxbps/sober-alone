"""Regression cases for author corrections, audience isolation and optional review."""

import json
import uuid
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from test_outline_cocreation import command, settle, start  # noqa: F401
from test_outline_cocreation import env as workshop_env
from test_workflow_service import FakeGraph, snapshot

from app.api.schemas.script_editor import ResumeWorkflowRequest
from app.script_editor.conversion.disclosure import DisclosurePlan, audience_material, validate_plan
from app.script_editor.graph import _route_after_normalize, _route_after_safety_check
from app.script_editor.nodes import quality_check, safety_check
from app.script_editor.outline import actions, nodes
from app.script_editor.outline.contracts import new_session
from app.script_editor.outline.revisions import OutlineRevision, apply_outline_input
from app.script_editor.services.workflow_service import ScriptEditorWorkflowService

env = workshop_env


@pytest.mark.asyncio
async def test_combined_answer_replaces_relation_motive_and_clue_without_touching_other_paragraph(
    monkeypatch,
):
    state = {
        "outline": "阿甲长期胁迫阿乙。\n\n阿乙因此计划报复，信是威胁证据。\n\n暴雨封闭了旅馆。",
        "outline_session": new_session(),
    }
    state["outline_session"].update(
        canon=["阿甲长期胁迫阿乙"],
        pending_input={
            "choice": "共同秘密",
            "other_text": "但阿甲从未逼迫阿乙；二人一直互利，无预谋。",
            "after": "review",
        },
    )

    async def model(schema, system, content):
        material = json.loads(content)
        assert material["本次作者输入"]["choice"] == "共同秘密"
        assert "从未逼迫" in material["本次作者输入"]["other_text"]
        return OutlineRevision(
            edits=[
                {"id": "p1", "content": "二人一直自愿互利。"},
                {"id": "p2", "content": "阿乙没有预谋，信记录了共同隐瞒的交易。"},
            ],
            canon=["自愿互利，没有长期胁迫", "无预谋"],
            summary="已取消胁迫，并调整动机与信件。",
        )

    monkeypatch.setattr(nodes, "structured", model)
    result = await apply_outline_input(state)
    assert "胁迫" not in result["outline"]
    assert result["outline"].endswith("暴雨封闭了旅馆。")
    assert result["outline_session"]["undo_stack"][-1]["outline"] == state["outline"]
    context = nodes.context({**state, **result}, result["outline_session"])
    assert "长期胁迫阿乙" not in context
    assert "无预谋" in context


@pytest.mark.asyncio
async def test_failed_revision_preserves_committed_text(monkeypatch):
    original = {"outline": "完整旧稿", "outline_session": new_session()}
    original["outline_session"]["pending_input"] = {"other_text": "修改关系"}
    before = deepcopy(original)
    monkeypatch.setattr(nodes, "structured", AsyncMock(side_effect=TimeoutError))
    with pytest.raises(TimeoutError):
        await apply_outline_input(original)
    assert original == before


@pytest.mark.asyncio
async def test_unselected_director_options_never_become_effective_facts(monkeypatch):
    from test_outline_cocreation import QUESTION

    from app.script_editor.outline.contracts import Direction

    monkeypatch.setattr(
        nodes,
        "structured",
        AsyncMock(
            return_value=Direction(
                action="ask",
                next_task="继续",
                question=QUESTION,
                ai_decisions=["未选择的预谋杀人结论"],
            )
        ),
    )
    result = await nodes.direct_outline({"outline_session": new_session(), "outline": "开篇"})
    assert result["outline_session"]["decisions"] == []
    assert "预谋杀人" not in nodes.context({"outline": "开篇"}, result["outline_session"])


@pytest.mark.asyncio
async def test_revision_undo_is_durable_and_stale_revision_is_rejected(env):
    runner, _, graph, _, _ = env
    thread, state = await start(env)
    before = state["state"]["outline"]
    await actions.queue_action(
        runner, thread, command("revise", state, other_text="改为合作关系"), "owner"
    )
    await settle(runner)
    service = ScriptEditorWorkflowService()
    revised = await service.get_state(thread)
    assert revised["state"]["outline_session"]["revision"] == 2
    assert revised["state"]["outline_session"]["canon"] == [
        *state["state"]["outline_session"]["canon"],
        "改为合作关系",
    ]
    with pytest.raises(ValueError, match="版本"):
        await actions.queue_action(
            runner, thread, command("revise", state, other_text="过期修改"), "owner"
        )
    undo = command("undo", revised)
    await actions.queue_action(runner, thread, undo, "owner")
    await settle(runner)
    restored = await ScriptEditorWorkflowService(graph).get_state(thread)
    assert restored["state"]["outline"] == before
    assert (
        restored["state"]["outline_session"]["canon"] == state["state"]["outline_session"]["canon"]
    )
    assert restored["state"]["outline_session"]["revision"] == 3
    duplicate = await actions.queue_action(runner, thread, undo, "owner")
    assert duplicate["operation_id"] == undo.request_id


def disclosure():
    return {
        "characters": [{"name": "甲"}, {"name": "乙"}],
        "game_start": "晚餐开始",
        "start_evidence": "晚餐开始。",
        "facts": [
            {
                "id": "f1",
                "quote": "晚餐开始。",
                "known_by": ["甲", "乙"],
                "actors": [],
                "before_start": True,
                "release": "public",
                "round": None,
            },
            {
                "id": "f2",
                "quote": "甲调换了杯子。",
                "known_by": ["甲"],
                "actors": ["甲"],
                "before_start": True,
                "release": "reveal",
                "round": None,
            },
            {
                "id": "f3",
                "quote": "乙独自到过仓库。",
                "known_by": ["乙"],
                "actors": ["乙"],
                "before_start": True,
                "release": "reveal",
                "round": None,
            },
            {
                "id": "f4",
                "quote": "随后鉴定发现两种药物。",
                "known_by": [],
                "actors": [],
                "before_start": False,
                "release": "round",
                "round": 1,
            },
        ],
    }


def test_personal_public_and_reveal_inputs_are_physically_separated():
    plan = disclosure()
    validate_plan(
        DisclosurePlan.model_validate(plan), "".join(f["quote"] for f in plan["facts"]), 2, 1
    )
    state = {"disclosure_plan": plan, "final_draft": "未知全知真相"}
    personal = json.dumps(audience_material(state, role="甲"), ensure_ascii=False)
    assert "调换了杯子" in personal
    assert "仓库" not in personal and "药物" not in personal and "全知真相" not in personal
    public = json.dumps(audience_material(state), ensure_ascii=False)
    assert "杯子" not in public
    assert "药物" in json.dumps(audience_material(state, scope="clues"), ensure_ascii=False)


@pytest.mark.parametrize(
    "mutation", ["source", "unknown_role", "own_action", "future", "round", "count"]
)
def test_invalid_disclosure_fails_closed(mutation):
    plan = disclosure()
    source = "".join(f["quote"] for f in plan["facts"])
    if mutation == "source":
        plan["facts"][1]["quote"] = "编造的事实"
    if mutation == "unknown_role":
        plan["facts"][1]["known_by"] += ["不存在的人"]
    if mutation == "own_action":
        plan["facts"][1]["known_by"] = []
    if mutation == "future":
        plan["facts"][3]["known_by"] = ["甲"]
    if mutation == "round":
        plan["facts"][3]["round"] = 9
    if mutation == "count":
        plan["characters"] = plan["characters"][:1]
    with pytest.raises(ValueError):
        validate_plan(DisclosurePlan.model_validate(plan), source, 2, 1)


@pytest.mark.parametrize(
    "report",
    [
        None,
        {"status": "blocked"},
        {"status": "incomplete"},
        {"status": "passed", "content_fingerprint": "old"},
    ],
)
def test_quality_report_never_gates_routing(report, monkeypatch):
    state = {"quality_report": report}
    assert _route_after_normalize(state) == "safety_check"
    monkeypatch.setattr(safety_check, "safety_approved", lambda _: True)
    assert _route_after_safety_check(state) == "save_to_database"


def test_report_target_uses_sorted_stable_id_not_ui_index():
    content = {
        "characters": [{"character_id": "a", "name": "甲"}, {"character_id": "z", "name": "乙"}]
    }
    target = quality_check.finding_target(content, "characters[1].character_script")
    reordered_ui = list(reversed(content["characters"]))
    assert next(c for c in reordered_ui if c["character_id"] == target["entity_id"])["name"] == "乙"
    assert target["label"] == "角色 → 乙 → 个人剧本"


@pytest.mark.asyncio
async def test_optional_check_calls_once_even_after_failure_and_edit(monkeypatch):
    live = snapshot(
        {"current_step": "review_game_data", "game_data_sections": {}}, ("review_game_data",)
    )

    class MutableGraph(FakeGraph):
        def update_state(self, config, values):
            live.values.update(values)

    graph = MutableGraph({"live": live})
    review = AsyncMock(return_value={"quality_report": {"status": "incomplete", "findings": []}})
    monkeypatch.setattr(quality_check, "check_game_quality", review)
    service = ScriptEditorWorkflowService(graph)
    await service.resume(
        "thread",
        ResumeWorkflowRequest(action="quality_check", game_data_sections={"title": "新稿"}),
    )
    await service.resume(
        "thread",
        ResumeWorkflowRequest(action="quality_check", game_data_sections={"title": "再改"}),
    )
    assert review.await_count == 1
    assert live.values["quality_check_attempted"]
    assert graph.invocations == []


@pytest.mark.asyncio
async def test_resume_request_id_checkpoint_and_refinement_limit(env, monkeypatch):
    runner, _, graph, _, _ = env
    thread, _ = await start(env)
    config = ScriptEditorWorkflowService.config(thread)
    await graph.aupdate_state(
        config,
        {
            "current_step": "review_first_draft",
            "outline_session": {},
            "first_draft": "作者稿",
            "refinement_counts": {"review_first_draft": 3},
        },
        as_node="generate_first_draft",
    )
    await graph.ainvoke(None, config)
    checkpoint = (await graph.aget_state(config)).config["configurable"]["checkpoint_id"]
    monkeypatch.setattr(runner, "_schedule", lambda _: None)
    with pytest.raises(ValueError, match="改进"):
        await runner.queue_resume(thread, ResumeWorkflowRequest(action="regenerate"), "owner")
    with pytest.raises(ValueError, match="建议"):
        await runner.queue_resume(
            thread, ResumeWorkflowRequest(action="regenerate", feedback="更克制"), "owner"
        )
    with pytest.raises(ValueError, match="新版本"):
        await runner.queue_resume(
            thread, ResumeWorkflowRequest(action="confirm", expected_checkpoint_id="old"), "owner"
        )
    request = ResumeWorkflowRequest(
        action="confirm",
        content="未保存的新稿",
        expected_checkpoint_id=checkpoint,
        request_id=str(uuid.uuid4()),
    )
    first = await runner.queue_resume(thread, request, "owner")
    second = await runner.queue_resume(thread, request, "owner")
    assert first["operation_id"] == second["operation_id"]
    with pytest.raises(ValueError, match="请求编号"):
        await runner.queue_resume(thread, request.model_copy(update={"content": "别的稿"}), "owner")


def test_terminal_graph_with_failed_asset_is_not_complete():
    live = snapshot(
        {
            "current_step": "generate_assets",
            "asset_progress": {"phases": [{"tasks": [{"id": "cover", "status": "failed"}]}]},
        }
    )
    response = ScriptEditorWorkflowService(FakeGraph({"live": live}))._live_response("thread", live)
    assert not response["is_complete"]


@pytest.mark.asyncio
async def test_asset_retry_survives_runner_restart_without_repeating_completed_task(
    env, monkeypatch
):
    import asyncio

    from app.script_editor.nodes import save
    from app.script_editor.services.operation_service import EditorOperationRunner
    from app.script_editor.services.progress_registry import asset_progress_registry

    runner, factory, graph, _, _ = env
    from app.db.models import EditorWorkflow

    thread = str(uuid.uuid4())
    async with factory() as db:
        db.add(
            EditorWorkflow(
                thread_id=thread,
                owner_key_hash="owner",
                workflow_mode="create",
                status="idle",
                current_step="generate_assets",
            )
        )
        await db.commit()
    config = ScriptEditorWorkflowService.config(thread)
    script_id = "recovery-assets"
    progress = {
        "phases": [
            {
                "id": "image",
                "tasks": [
                    {"id": "cover", "status": "failed"},
                    {"id": "avatar_a", "status": "complete"},
                ],
            }
        ],
        "isComplete": False,
    }
    await graph.aupdate_state(
        config,
        {
            "outline_session": {},
            "current_step": "generate_assets",
            "script_id": script_id,
            "asset_progress": progress,
        },
        as_node="generate_assets",
    )
    asset_progress_registry.init(script_id, progress["phases"])
    asset_progress_registry.register_thread(script_id, thread)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def retry(sid, task_id, _state):
        calls.append(task_id)
        if not asset_progress_registry.snapshot(sid):
            asset_progress_registry.init(sid, _state["asset_progress"]["phases"])
        asset_progress_registry.update_task(sid, task_id, "running")
        asset_progress_registry.publish(sid)
        started.set()
        await release.wait()
        asset_progress_registry.update_task(sid, task_id, "complete")
        asset_progress_registry.complete_if_all(sid, {"complete", "skipped"})
        asset_progress_registry.publish(sid)

    monkeypatch.setattr(save, "retry_single_asset", retry)
    request = ResumeWorkflowRequest(
        action="retry_asset", asset_task_id="cover", request_id=str(uuid.uuid4())
    )
    accepted = await runner.queue_resume(thread, request, "owner")
    await asyncio.wait_for(started.wait(), 5)
    duplicate = await runner.queue_resume(thread, request, "owner")
    assert duplicate["operation_id"] == accepted["operation_id"]
    await runner.shutdown()
    asset_progress_registry.reset(script_id)
    release.set()
    second = EditorOperationRunner()
    try:
        await second.recover_pending()
        await settle(second)
        final = await ScriptEditorWorkflowService(graph).get_state(thread)
        assert final["is_complete"], (calls, final, (await graph.aget_state(config)).next)
        assert calls == ["cover", "cover"]
        assert final["state"]["asset_progress"]["phases"][0]["tasks"][1]["status"] == "complete"
    finally:
        await second.shutdown()
        asset_progress_registry.reset(script_id)


@pytest.mark.asyncio
async def test_stop_questions_never_promotes_recommended_option_to_author_canon(monkeypatch):
    from test_outline_cocreation import QUESTION

    session = new_session()
    session.update(
        canon=["双方一直互利，从无胁迫"],
        pending_question={**QUESTION, "id": "q"},
        questions_stopped=True,
    )
    result = await nodes.wait_for_answer({"outline_session": session})
    assert result["outline_session"]["canon"] == session["canon"]
    assert result["outline_session"]["decisions"] == []
    assert result["outline_session"]["next_action"] == "finalize"


@pytest.mark.asyncio
async def test_committed_refinement_is_not_generated_again_after_operation_restart(
    env, monkeypatch
):
    from app.db.models import EditorOperation

    runner, factory, graph, _, _ = env
    thread, _ = await start(env)
    request_id = str(uuid.uuid4())
    config = ScriptEditorWorkflowService.config(thread)
    await graph.aupdate_state(
        config,
        {
            "outline_session": {},
            "current_step": "review_first_draft",
            "first_draft": "已经改写成功的新稿",
            "completed_refinements": [request_id],
            "refinement_counts": {"review_first_draft": 1},
        },
        as_node="generate_first_draft",
    )
    await graph.ainvoke(None, config)
    async with factory() as db:
        db.add(
            EditorOperation(
                operation_id=request_id,
                thread_id=thread,
                kind="resume",
                status="running",
                target_step="review_first_draft",
                request_payload={
                    "action": "regenerate",
                    "request_id": request_id,
                    "feedback": "更克制",
                },
            )
        )
        await db.commit()
    regenerate = AsyncMock(side_effect=AssertionError("must not call model again"))
    monkeypatch.setattr(ScriptEditorWorkflowService, "resume", regenerate)
    await runner.recover_pending()
    await settle(runner)
    regenerate.assert_not_awaited()
    state = await ScriptEditorWorkflowService(graph).get_state(thread)
    assert state["state"]["first_draft"] == "已经改写成功的新稿"
    assert state["state"]["refinement_counts"]["review_first_draft"] == 1


@pytest.mark.parametrize(
    "quote", ["甲不知道乙进过仓库。", "甲不清楚杯中有毒。", "甲没有意识到这是毒物。"]
)
def test_negative_knowledge_cannot_leak_through_role_or_public_material(quote):
    plan = disclosure()
    plan["facts"].append(
        {
            "id": "hidden",
            "quote": quote,
            "known_by": ["甲"],
            "actors": [],
            "before_start": True,
            "release": "reveal",
        }
    )
    source = "".join(f["quote"] for f in plan["facts"])
    with pytest.raises(ValueError, match="不知情"):
        validate_plan(DisclosurePlan.model_validate(plan), source, 2, 1)
    # Also protect old persisted plans that predate this validation.
    material = json.dumps(
        audience_material({"disclosure_plan": plan}, role="甲"), ensure_ascii=False
    )
    assert quote not in material
    assert "调换了杯子" in material


@pytest.mark.asyncio
async def test_disclosure_repairs_source_reference_without_exposing_unknown_clause(monkeypatch):
    from app.script_editor.conversion import disclosure as module

    class Model:
        def model_copy(self, update):
            assert update["max_tokens"] >= 16000
            return self

    source = "晚餐开始。甲调换了杯子，却不知道乙已进过仓库。乙独自到过仓库。"
    calls = []

    async def extract(_model, _schema, _system, material):
        calls.append(deepcopy(material))
        assert "甲必须死在序幕" not in json.dumps(material, ensure_ascii=False)
        return DisclosurePlan.model_validate(
            {
                "characters": [{"name": "甲"}, {"name": "乙"}],
                "game_start": "晚餐开始",
                "start_source_id": 1,
                "facts": [
                    {
                        "id": "f1",
                        "source_id": 1,
                        "known_by": [],
                        "actors": [],
                        "before_start": True,
                        "release": "public",
                    },
                    {
                        "id": "f2",
                        "source_id": 2,
                        "quote": "甲调换了杯子" if len(calls) > 1 else "",
                        "known_by": ["甲"],
                        "actors": ["甲"],
                        "before_start": True,
                        "release": "reveal",
                    },
                    {
                        "id": "f3",
                        "source_id": 3,
                        "known_by": ["乙"],
                        "actors": ["乙"],
                        "before_start": True,
                        "release": "reveal",
                    },
                ],
            }
        )

    monkeypatch.setattr(module, "invoke", extract)
    plan = await module.extract_plan(
        Model(),
        {
            "final_draft": source,
            "player_count": 2,
            "num_clue_rounds": 1,
            "outline_session": {"canon": ["甲必须死在序幕"]},
        },
    )
    assert len(calls) == 2
    assert "不知情" in calls[1]["必须修复的校验问题"]
    material = json.dumps(
        audience_material({"disclosure_plan": plan}, role="甲"), ensure_ascii=False
    )
    assert "调换了杯子" in material and "仓库" not in material
