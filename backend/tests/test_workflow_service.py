from types import SimpleNamespace

import pytest

from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowNotFoundError,
)


def snapshot(values=None, next_nodes=(), checkpoint_id="cp-1"):
    return SimpleNamespace(
        values=values or {},
        next=next_nodes,
        tasks=(),
        config={"configurable": {"checkpoint_id": checkpoint_id}},
        created_at="2026-08-13T00:00:00Z",
    )


class FakeGraph:
    def __init__(self, states):
        self.states = states
        self.updates = []
        self.invocations = []

    def get_state(self, config):
        checkpoint_id = config["configurable"].get("checkpoint_id")
        if checkpoint_id:
            return self.states.get(checkpoint_id, snapshot())
        return self.states.get("live", snapshot())

    def get_state_history(self, _config):
        return list(self.states.get("history", []))

    def update_state(self, config, values):
        self.updates.append((config, values))

    async def ainvoke(self, value, config):
        self.invocations.append((value, config))


def test_interrupt_reconstruction_and_state_serialization_are_stable():
    state = snapshot(
        {
            "current_step": "generate_outline",
            "outline": "线索大纲",
            "prompts": {"generate_outline": "提示词"},
        },
        ("review_outline",),
    )

    interrupt = ScriptEditorWorkflowService.extract_interrupt(state)

    assert interrupt["step"] == "review_outline"
    assert interrupt["generated_content"] == "线索大纲"
    assert interrupt["prompt_used"] == "提示词"
    assert "owner_uuid" not in ScriptEditorWorkflowService.serialize_state(state.values)


def test_history_and_checkpoint_use_same_wire_contract():
    checkpoint = snapshot({"current_step": "review_final", "final_draft": "终稿"})
    service = ScriptEditorWorkflowService(
        FakeGraph({"live": checkpoint, "cp-1": checkpoint, "history": [checkpoint]})
    )

    history = service.get_history("thread")
    selected = service.get_checkpoint("thread", "cp-1")

    assert history["checkpoints"][0]["checkpoint_id"] == "cp-1"
    assert selected["checkpoint_id"] == "cp-1"
    assert selected["interrupt"]["step"] == "review_final"


@pytest.mark.asyncio
async def test_forking_init_checkpoint_is_read_only_and_does_not_reinvoke_graph():
    initial = snapshot({"current_step": "init", "user_idea": "雾港"})
    graph = FakeGraph({"cp-init": initial, "live": initial})
    service = ScriptEditorWorkflowService(graph)

    result = await service.fork("thread", "cp-init", {"user_idea": "新雾港"})

    assert result["current_step"] == "init"
    assert result["interrupt"] is None
    assert graph.updates[0][1] == {"user_idea": "新雾港"}
    assert graph.invocations == []


def test_missing_workflow_raises_domain_error():
    service = ScriptEditorWorkflowService(FakeGraph({}))

    with pytest.raises(WorkflowNotFoundError):
        service.get_state("missing")


def test_terminal_error_is_not_reported_as_completed():
    failed = snapshot(
        {
            "current_step": "save_to_database",
            "error_message": "保存失败: database is locked",
            "safety_rejection_reason": "",
        }
    )
    service = ScriptEditorWorkflowService(FakeGraph({"live": failed}))

    result = service.get_state("thread")

    assert result["is_complete"] is False
    assert result["state"]["error_message"] == "保存失败: database is locked"
    assert "safety_rejection_reason" in result["state"]
