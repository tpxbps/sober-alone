import json

import httpx
import pytest

from app.core import deepseek_fallback as fallback
from app.core.config import settings
from app.core.inference import InferenceRecoveryError, InferenceScope, inference_scope


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setattr(settings, "TOKENDANCE_BASE_URL", "https://tokendance.space/gateway")
    monkeypatch.setattr(settings, "DEEPSEEK_API_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "official-test-credential")
    monkeypatch.setattr(fallback, "_cooldown_until", 0)


def request():
    return httpx.Request(
        "POST",
        "https://tokendance.space/gateway/v1/chat/completions",
        headers={
            "Authorization": "Bearer gateway-test-credential",
            "X-App-URL": "https://example.test/",
        },
        json={
            "model": "deepseek-v4.1-flash",
            "messages": [],
            "tools": [{"type": "function"}],
            "thinking": {"type": "disabled"},
        },
        extensions={"timeout": {"read": 240}},
    )


@pytest.mark.asyncio
async def test_creator_fallback_preserves_tools_but_never_gateway_credentials():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(503 if req.url.host == "tokendance.space" else 200, content=b"result")

    transport = fallback.AsyncDeepSeekTransport(httpx.MockTransport(handler))
    with inference_scope(InferenceScope("creator", lambda: "creator", True)):
        response = await transport.handle_async_request(request())
        assert await response.aread() == b"result"
        await transport.handle_async_request(request())
    assert [r.url.host for r in seen] == [
        "tokendance.space",
        "api.deepseek.com",
        "api.deepseek.com",
    ]
    assert seen[0].extensions["timeout"]["read"] == 45
    official = seen[1]
    assert official.headers["Authorization"] == "Bearer official-test-credential"
    assert "X-App-URL" not in official.headers
    assert official.extensions["timeout"]["read"] == 240
    assert json.loads(official.content)["model"] == "deepseek-flash"
    assert json.loads(official.content)["tools"] == [{"type": "function"}]


@pytest.mark.parametrize(
    "scope",
    [None, InferenceScope("user:a", lambda: "user"), InferenceScope("trial", lambda: "trial")],
)
def test_player_and_unscoped_requests_never_use_fallback(scope):
    from contextlib import nullcontext

    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(503)

    transport = fallback.DeepSeekTransport(httpx.MockTransport(handler))
    with inference_scope(scope) if scope else nullcontext():
        assert transport.handle_request(request()).status_code == 503
    assert seen == ["tokendance.space"]


@pytest.mark.parametrize("action", ["api_key_quota", "top_up_balance", "reauthorize_api_key"])
def test_recovery_never_switches_billing(action):
    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(429, headers={"TokenDance-Recovery-Action": action})

    with inference_scope(InferenceScope("creator", lambda: "creator", True)):
        with pytest.raises(InferenceRecoveryError):
            fallback.DeepSeekTransport(httpx.MockTransport(handler)).handle_request(request())
    assert seen == ["tokendance.space"]


@pytest.mark.asyncio
async def test_no_midstream_fallback_or_duplicate_partial_output():
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"first"
            raise httpx.ReadTimeout("interrupted")

    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(200, stream=BrokenStream())

    with inference_scope(InferenceScope("creator", lambda: "creator", True)):
        response = await fallback.AsyncDeepSeekTransport(
            httpx.MockTransport(handler)
        ).handle_async_request(request())
        chunks = response.aiter_raw()
        assert await anext(chunks) == b"first"
        with pytest.raises(httpx.ReadTimeout):
            await anext(chunks)
    assert seen == ["tokendance.space"]


@pytest.mark.asyncio
async def test_first_byte_timeout_falls_back_once():
    class SilentStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadTimeout("no first byte")
            yield b""  # pragma: no cover

    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(200, stream=SilentStream()) if len(seen) == 1 else httpx.Response(503)

    with inference_scope(InferenceScope("creator", lambda: "creator", True)):
        response = await fallback.AsyncDeepSeekTransport(
            httpx.MockTransport(handler)
        ).handle_async_request(request())
    assert response.status_code == 503
    assert seen == ["tokendance.space", "api.deepseek.com"]
