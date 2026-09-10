import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.game import resource_revision
from app.game.content_quality import content_fingerprint
from app.game.flow_controller import GameFlowController
from app.services.game_presenter import GameStatePresenter
from app.services.game_runtime import build_runtime_snapshot


def publish_manifest(root, script):
    fingerprint = content_fingerprint(script)
    namespace = f"{script['script_id']}__{fingerprint}"
    path = root / "scripts" / namespace / "resources.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "ready", "content_fingerprint": fingerprint}))
    return namespace, path


def test_old_session_keeps_legacy_assets_while_new_session_uses_its_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(resource_revision, "settings", SimpleNamespace(audio_dir=tmp_path))
    old = build_runtime_snapshot({"script_id": "script", "title": "Old", "characters": []})
    new = deepcopy(old)
    new["full_truth"] = "Revised truth"
    namespace, _ = publish_manifest(tmp_path, new)
    assert resource_revision.resource_namespace(old) == "script"
    assert resource_revision.resource_namespace(new) == namespace
    assert GameStatePresenter.script(old)["resource_namespace"] == "script"
    assert GameStatePresenter.script(new)["resource_namespace"] == namespace

    session = SimpleNamespace(script_id="script", current_stage="intro", current_round=0)
    assert GameFlowController(session, old, None).resource_namespace == "script"
    assert GameFlowController(session, new, None).resource_namespace == namespace
    new["cover_image_url"] = "changed-cover.png"
    assert resource_revision.resource_namespace(new) == namespace
    new["full_truth"] = "Third version without published assets"
    assert resource_revision.resource_namespace(new) == "script"


@pytest.mark.parametrize("status, fingerprint", [("building", "same"), ("ready", "wrong")])
def test_incomplete_revision_does_not_silently_play_legacy_audio(
    tmp_path, monkeypatch, status, fingerprint
):
    monkeypatch.setattr(resource_revision, "settings", SimpleNamespace(audio_dir=tmp_path))
    script = {"script_id": "script", "characters": []}
    _, path = publish_manifest(tmp_path, script)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "content_fingerprint": content_fingerprint(script)
                if fingerprint == "same"
                else fingerprint,
            }
        )
    )
    with pytest.raises(ValueError, match="resources"):
        resource_revision.resource_namespace(script)


@pytest.mark.asyncio
async def test_restored_agent_memory_uses_session_snapshot_not_current_script(
    tmp_path, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.services import game_service
    from app.services.game_runtime import FlowControllerRegistry

    monkeypatch.setattr(resource_revision, "settings", SimpleNamespace(audio_dir=tmp_path))
    monkeypatch.setattr(game_service, "_flow_controllers", FlowControllerRegistry())
    old = build_runtime_snapshot({"script_id": "script", "characters": []})
    new = deepcopy(old)
    new["full_truth"] = "Revised truth"
    namespace, _ = publish_manifest(tmp_path, new)
    requested = []

    def manager(session_id, script_id):
        requested.append((session_id, script_id))
        return SimpleNamespace(agents={}, initialize_agents=AsyncMock())

    monkeypatch.setattr(game_service, "get_agent_manager", manager)
    loader = AsyncMock()
    monkeypatch.setattr(game_service.GameRuntimeRepository, "load_session_script", loader)
    for session_id, snapshot in (("old-session", old), ("new-session", new)):
        session = SimpleNamespace(
            script_id="script",
            current_stage="intro",
            current_round=0,
            human_character_id="human",
        )
        loader.return_value = snapshot
        database = SimpleNamespace(
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: session))
        )
        controller = await game_service.ensure_flow_controller(session_id, database)
        assert controller.script_data is snapshot
    assert requested == [("old-session", "script"), ("new-session", namespace)]
