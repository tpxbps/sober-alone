import asyncio
import json

import httpx
import pytest

from app.core.inference import InferenceRecoveryError
from app.services import tts_service


@pytest.mark.asyncio
async def test_static_narration_reads_final_paragraph_after_sentence_chunks(monkeypatch):
    monkeypatch.setattr(tts_service.settings, "MIMO_API_KEY", "test-only")
    text = "很久以前，我们在那间广播室认识。" * 100 + "最后，我仍记得她没有说完的话。"
    calls = []

    async def synthesize(part, *args):
        calls.append(part)
        return b"complete-part"

    monkeypatch.setattr(tts_service, "_mimo_single_call", synthesize)
    monkeypatch.setattr(tts_service, "concatenate_wav", lambda parts, **kwargs: b"".join(parts))
    result = await tts_service.TTSService.synthesize_static(text, "自然叙述")
    assert "".join(calls) == text
    assert len(calls) > 1
    assert all(len(part) <= 600 for part in calls)
    assert calls[-1].endswith("没有说完的话。")
    assert result == b"complete-part" * len(calls)


@pytest.mark.asyncio
async def test_length_limited_audio_is_not_accepted_as_complete(monkeypatch):
    original_client = httpx.AsyncClient
    response = {"choices": [{"finish_reason": "length", "message": {"audio": {"data": "YWJj"}}}]}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=json.dumps(response))
    )
    monkeypatch.setattr(
        tts_service.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    assert (
        await tts_service._mimo_single_call(
            "未读完的文字", "自然", "冰糖", "https://tts.invalid", "test-only"
        )
        is None
    )


@pytest.mark.asyncio
async def test_gateway_narration_limits_across_jobs_and_releases_cancelled_slot(monkeypatch):
    monkeypatch.setattr(tts_service.settings, "INFERENCE_BACKEND", "tokendance")
    monkeypatch.setattr(tts_service, "MIMO_GATEWAY_INTERVAL", 0)
    active = 0
    peak = 0
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def request(text, *args):
        nonlocal active, peak
        calls.append(text)
        active += 1
        peak = max(peak, active)
        entered.set()
        try:
            await release.wait()
            return b"audio"
        finally:
            active -= 1

    monkeypatch.setattr(tts_service, "_mimo_request", request)

    async def call(text):
        return await tts_service._mimo_single_call(text, "", "", "", "")

    first = asyncio.create_task(call("first"))
    await entered.wait()
    siblings = [asyncio.create_task(call(str(i))) for i in range(8)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    siblings[-1].cancel()
    first.cancel()
    await asyncio.gather(first, siblings[-1], return_exceptions=True)
    release.set()
    assert await asyncio.gather(*siblings[:-1]) == [b"audio"] * 7
    assert peak <= 2
    assert active == 0
    assert "7" not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, expected_calls", [(429, 2), (503, 1), ("quota", 1)])
async def test_narration_retry_is_bounded_and_never_retries_account_recovery(
    monkeypatch, failure, expected_calls
):
    monkeypatch.setattr(tts_service.settings, "INFERENCE_BACKEND", "tokendance")
    monkeypatch.setattr(tts_service, "MIMO_GATEWAY_INTERVAL", 0)
    calls = 0

    async def request(*args):
        nonlocal calls
        calls += 1
        if failure == "quota":
            raise InferenceRecoveryError("api_key_quota")
        response = httpx.Response(failure, request=httpx.Request("POST", "https://tts.invalid"))
        response.raise_for_status()

    monkeypatch.setattr(tts_service, "_mimo_request", request)
    if failure == "quota":
        with pytest.raises(InferenceRecoveryError):
            await tts_service._mimo_single_call("text", "", "", "", "")
    else:
        assert await tts_service._mimo_single_call("text", "", "", "", "") is None
    assert calls == expected_calls
