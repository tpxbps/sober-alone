from app.script_editor.services.progress_registry import WorkflowProgressRegistry


def test_snapshot_is_deep_copy_and_late_subscriber_can_read_full_state():
    registry = WorkflowProgressRegistry("test_progress")
    registry.init(
        "script",
        [{"id": "phase", "tasks": [{"id": "task", "status": "pending"}]}],
    )
    registry.update_task("script", "task", "skipped", "optional key missing")

    first = registry.snapshot("script")
    assert first is not None
    first["phases"][0]["tasks"][0]["status"] = "corrupted"
    second = registry.snapshot("script")

    assert second["phases"][0]["tasks"][0] == {
        "id": "task",
        "status": "skipped",
        "reason": "optional key missing",
    }


def test_failed_task_never_marks_progress_complete():
    registry = WorkflowProgressRegistry("test_progress")
    registry.init(
        "script",
        [{"id": "phase", "tasks": [{"id": "task", "status": "pending"}]}],
    )
    registry.update_task("script", "task", "failed", "provider error")

    assert registry.complete_if_all("script", {"complete", "skipped"}) is False
    assert registry.snapshot("script")["isComplete"] is False
