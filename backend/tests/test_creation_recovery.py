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
