"""Opt-in creator fallback, before any response is delivered to the model SDK.

Player scopes never qualify. Credentials are resolved again on every dispatch;
the official request contains only the site's official DeepSeek credential.
"""

import json
import logging
import time

import httpx

from app.core.config import settings
from app.core.inference import _scope, check_gateway_response

logger = logging.getLogger(__name__)
_cooldown_until = 0.0


def _eligible(request: httpx.Request) -> bool:
    scope = _scope.get()
    return bool(
        scope
        and scope.allow_deepseek_fallback
        and settings.DEEPSEEK_API_KEY
        and request.url
        == httpx.URL(settings.TOKENDANCE_BASE_URL.rstrip("/") + "/v1/chat/completions")
        and json.loads(request.content).get("model") == "deepseek-v4.1-flash"
    )


def _official(request: httpx.Request) -> httpx.Request:
    # Never forward the gateway's Authorization header, cookies or extensions.
    base = httpx.URL(settings.DEEPSEEK_API_BASE_URL)
    if base.scheme != "https" or base.host != "api.deepseek.com":
        raise ValueError("DeepSeek fallback requires the official HTTPS endpoint")
    scope = _scope.get()
    if scope is None or not scope.allow_deepseek_fallback:
        raise ValueError("This inference scope cannot use the site fallback")
    scope.resolve_key()  # Re-check revocation/availability before switching routes.
    body = json.loads(request.content)
    body["model"] = "deepseek-flash"
    return httpx.Request(
        "POST",
        str(base).rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + settings.DEEPSEEK_API_KEY},
        json=body,
        extensions={"timeout": dict(request.extensions.get("timeout", {}))},
    )


def _bounded(request: httpx.Request) -> httpx.Request:
    timeout = dict(request.extensions.get("timeout", {}))
    timeout["read"] = min(timeout.get("read") or 45, 45)
    return httpx.Request(
        request.method,
        request.url,
        headers=request.headers,
        content=request.content,
        extensions={**request.extensions, "timeout": timeout},
    )


def _failed(response: httpx.Response) -> bool:
    check_gateway_response(response)  # Quota and authorization are never bypassed.
    return response.status_code in {408, 429} or response.status_code >= 500


def _record_fallback():
    global _cooldown_until
    _cooldown_until = time.monotonic() + 60
    logger.warning("Creator DeepSeek gateway unavailable; using official DeepSeek for 60 seconds")


class _SyncStream(httpx.SyncByteStream):
    def __init__(self, first, rest, original):
        self.first, self.rest, self.original = first, rest, original

    def __iter__(self):
        yield self.first
        yield from self.rest

    def close(self):
        self.original.close()


class _AsyncStream(httpx.AsyncByteStream):
    def __init__(self, first, rest, original):
        self.first, self.rest, self.original = first, rest, original

    async def __aiter__(self):
        yield self.first
        async for chunk in self.rest:
            yield chunk

    async def aclose(self):
        await self.original.aclose()


class DeepSeekTransport(httpx.BaseTransport):
    def __init__(self, transport=None):
        self.transport = transport or httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        if not _eligible(request):
            return self.transport.handle_request(request)
        if time.monotonic() < _cooldown_until:
            return self.transport.handle_request(_official(request))
        response = None
        try:
            response = self.transport.handle_request(_bounded(request))
            if not _failed(response):
                iterator = iter(response.stream)
                first = next(iterator, b"")
                response.stream = _SyncStream(first, iterator, response.stream)
                return response
        except httpx.TransportError:
            pass
        except BaseException:
            if response is not None:
                response.close()
            raise
        if response is not None:
            response.close()
        _record_fallback()
        return self.transport.handle_request(_official(request))

    def close(self):
        self.transport.close()


class AsyncDeepSeekTransport(httpx.AsyncBaseTransport):
    def __init__(self, transport=None):
        self.transport = transport or httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request):
        if not _eligible(request):
            return await self.transport.handle_async_request(request)
        if time.monotonic() < _cooldown_until:
            return await self.transport.handle_async_request(_official(request))
        response = None
        try:
            response = await self.transport.handle_async_request(_bounded(request))
            if not _failed(response):
                iterator = response.stream.__aiter__()
                first = await anext(iterator, b"")
                response.stream = _AsyncStream(first, iterator, response.stream)
                return response
        except httpx.TransportError:
            pass
        except BaseException:
            if response is not None:
                await response.aclose()
            raise
        if response is not None:
            await response.aclose()
        _record_fallback()
        return await self.transport.handle_async_request(_official(request))

    async def aclose(self):
        await self.transport.aclose()
