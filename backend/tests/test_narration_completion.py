import json

import httpx
import pytest

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
