import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.inference import InferenceRecoveryError, gather_inference


@pytest.mark.asyncio
async def test_account_recovery_cancels_pending_assets_even_with_partial_results():
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def pending():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def failed():
        await started.wait()
        try:
            raise InferenceRecoveryError("api_key_quota")
        except InferenceRecoveryError as cause:
            raise RuntimeError("SDK transport wrapper") from cause

    with pytest.raises(InferenceRecoveryError, match="api_key_quota"):
        await gather_inference(pending(), failed(), return_exceptions=True)
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_partial_assets_remain_available_on_ordinary_failure():
    async def failed():
        raise ValueError("invalid image")

    result = await gather_inference(
        AsyncMock(return_value="image.png")(), failed(), return_exceptions=True
    )
    assert result[0] == "image.png"
    assert isinstance(result[1], ValueError)


@pytest.mark.asyncio
async def test_vector_account_failure_does_not_retry(monkeypatch):
    from app.script_editor.asset_generation import service
    from app.script_editor.services import chroma_ingest

    ingest = AsyncMock(side_effect=InferenceRecoveryError("top_up_balance"))
    monkeypatch.setattr(chroma_ingest, "ingest_character_async", ingest)
    monkeypatch.setattr(service, "_update_task_status", lambda *args: None)
    with pytest.raises(InferenceRecoveryError, match="top_up_balance"):
        await service._run_vectorize(
            "script",
            {"character_scripts": {"Alice": "personal script"}},
            [{"character_id": "alice", "name": "Alice"}],
            {"vector_alice"},
        )
    assert ingest.await_count == 1


@pytest.mark.asyncio
async def test_parallel_asset_retries_only_regenerate_once(monkeypatch):
    from types import SimpleNamespace

    from app.api.routes.script_editor_routes import assets
    from app.script_editor.nodes import save

    progress = {"phases": [{"tasks": [{"id": "cover", "status": "failed"}]}]}
    state = SimpleNamespace(values={"script_id": "script", "asset_progress": progress})
    graph = SimpleNamespace(aget_state=AsyncMock(return_value=state), aupdate_state=AsyncMock())
    monkeypatch.setattr(assets, "_authorize_thread", AsyncMock())
    monkeypatch.setattr(assets, "get_script_gen_graph", lambda: graph)
    monkeypatch.setattr(save, "get_asset_progress", lambda _: progress)

    async def generate(*args):
        await asyncio.sleep(0)
        progress["phases"][0]["tasks"][0]["status"] = "complete"

    regenerate = AsyncMock(side_effect=generate)
    monkeypatch.setattr(save, "retry_single_asset", regenerate)
    results = await asyncio.gather(
        *(assets.retry_asset_task("asset-thread", "cover", "owner") for _ in range(4))
    )
    assert all(r["task_status"] == "complete" for r in results)
    assert regenerate.await_count == 1

    progress["phases"][0]["tasks"][0]["status"] = "failed"
    regenerate.side_effect = InferenceRecoveryError("api_key_quota")
    with pytest.raises(InferenceRecoveryError):
        await assets.retry_asset_task("asset-thread", "cover", "owner")
    assert (
        graph.aupdate_state.call_args.args[1]["asset_progress"]["phases"][0]["tasks"][0]["status"]
        == "failed"
    )


@pytest.mark.asyncio
async def test_quota_interruption_keeps_completed_assets_and_persists_retryable_tasks(monkeypatch):
    from types import SimpleNamespace

    from app.core.config import Settings
    from app.script_editor.asset_generation import service
    from app.script_editor.services.workflow_service import ScriptEditorWorkflowService

    monkeypatch.setattr(Settings, "get_api_key", lambda *_: "test-credential")
    completed = asyncio.Event()

    async def vector(script_id, *_):
        service._update_task_status(script_id, "vector_alice", "complete")
        completed.set()

    async def image(*_):
        await completed.wait()
        raise InferenceRecoveryError("api_key_quota")

    async def audio(*_):
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_run_vectorize", vector)
    monkeypatch.setattr(service, "_run_images", image)
    monkeypatch.setattr(service, "_run_tts", audio)
    save_urls = AsyncMock()
    monkeypatch.setattr(service.ScriptRepository, "update_asset_urls", save_urls)
    state = {
        "script_id": "quota-interrupted",
        "characters": [{"character_id": "alice", "name": "Alice"}],
        "character_scripts": {"Alice": "personal script"},
    }
    with pytest.raises(InferenceRecoveryError, match="api_key_quota"):
        await service.AssetGenerationService().generate(state)
    progress = service.get_asset_progress(state["script_id"])
    statuses = {
        task["id"]: task["status"] for phase in progress["phases"] for task in phase["tasks"]
    }
    assert statuses["vector_alice"] == "complete"
    assert all(value == "failed" for key, value in statuses.items() if key != "vector_alice")
    save_urls.assert_awaited_once()

    graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values=state)), aupdate_state=AsyncMock()
    )
    await ScriptEditorWorkflowService(graph).persist_asset_progress("workflow")
    assert graph.aupdate_state.call_args.args[1] == {"asset_progress": progress}
