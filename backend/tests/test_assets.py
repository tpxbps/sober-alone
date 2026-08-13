import pytest

from app.script_editor.nodes import save


@pytest.mark.asyncio
async def test_optional_asset_tasks_are_skipped_without_keys(monkeypatch):
    monkeypatch.setattr(save.settings, "ZHIPUAI_API_KEY", None)
    monkeypatch.setattr(save.settings, "DOUBAO_API_KEY", None)
    monkeypatch.setattr(save.settings, "MIMO_API_KEY", None)
    script_id = "test-no-assets"

    await save.generate_assets(
        {
            "script_id": script_id,
            "characters": [{"character_id": "char-a", "name": "甲"}],
            "game_full_process": [{"type": "initial"}, {"type": "review"}],
        }
    )
    progress = save.get_asset_progress(script_id)

    assert progress is not None
    assert progress["isComplete"] is True
    tasks = [task for phase in progress["phases"] for task in phase["tasks"]]
    assert tasks
    assert {task["status"] for task in tasks} == {"skipped"}
    assert all(task.get("reason") for task in tasks)
