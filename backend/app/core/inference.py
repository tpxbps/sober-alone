"""Request-scoped gateway authentication. Never put credentials in graph state."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

import httpx

from app.core.config import settings

RECOVERY_ACTIONS = frozenset({"top_up_balance", "reauthorize_api_key", "api_key_quota"})


class InferenceRecoveryError(RuntimeError):
    def __init__(self, action: str, *, status: int = 402):
        self.action = action if action in RECOVERY_ACTIONS else ""
        self.status = status
        super().__init__(f"模型账户需要处理：{self.action or 'provider_error'}")


def raise_for_inference_recovery(error: BaseException) -> None:
    """SDKs wrap transport-hook exceptions; do not turn recovery into fallback."""
    pending = [error]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        if isinstance(current, InferenceRecoveryError):
            raise current
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)


def retryable_gateway_error(error: Exception) -> bool:
    """Retry transport failures once; account recovery must reach the caller."""
    from openai import APIConnectionError, APIStatusError

    try:
        raise_for_inference_recovery(error)
    except InferenceRecoveryError:
        return False
    return isinstance(error, (APIConnectionError, httpx.TransportError)) or (
        isinstance(error, APIStatusError)
        and (error.status_code in {408, 429} or error.status_code >= 500)
    )


def model_retry_middleware():
    from langchain.agents.middleware import ModelRetryMiddleware

    if settings.INFERENCE_BACKEND == "tokendance":
        return ModelRetryMiddleware(
            max_retries=1,
            retry_on=retryable_gateway_error,
            on_failure="error",
            backoff_factor=2.0,
            initial_delay=1.0,
        )
    return ModelRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0)


def tool_retry_middleware():
    from langchain.agents.middleware import ToolRetryMiddleware

    if settings.INFERENCE_BACKEND == "tokendance":
        return ToolRetryMiddleware(
            max_retries=1,
            retry_on=retryable_gateway_error,
            on_failure="error",
            backoff_factor=2.0,
            initial_delay=1.0,
        )
    return ToolRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0)


@dataclass(frozen=True)
class InferenceScope:
    reference: str
    resolve_key: Callable[[], str] = field(repr=False, compare=False)


_scope: ContextVar[InferenceScope | None] = ContextVar("inference_scope", default=None)


@contextmanager
def inference_scope(scope: InferenceScope) -> Iterator[None]:
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def gateway_available() -> bool:
    return _scope.get() is not None or (
        not settings.TOKENDANCE_REQUIRE_SCOPE and bool(settings.TOKENDANCE_API_KEY)
    )


def gateway_key() -> str:
    scope = _scope.get()
    value = (
        scope.resolve_key()
        if scope
        else (settings.TOKENDANCE_API_KEY if not settings.TOKENDANCE_REQUIRE_SCOPE else None)
    )
    if not value:
        raise InferenceRecoveryError("reauthorize_api_key", status=401)
    return value


def feature_available(provider: str) -> bool:
    return bool(settings.get_api_key(provider))


class GatewayAuth(httpx.Auth):
    """Resolve at dispatch, including SDK retries and cached model instances."""

    def auth_flow(self, request: httpx.Request):
        expected = httpx.URL(settings.TOKENDANCE_BASE_URL)
        if (request.url.scheme, request.url.host, request.url.port) != (
            expected.scheme,
            expected.host,
            expected.port,
        ):
            raise ValueError("Gateway credentials cannot be sent to another origin")
        request.headers["Authorization"] = "Bearer " + gateway_key()
        if settings.TOKENDANCE_APP_URL:
            request.headers["X-App-URL"] = settings.TOKENDANCE_APP_URL
        yield request


def check_gateway_response(response: httpx.Response) -> None:
    if response.is_error:
        action = response.headers.get("TokenDance-Recovery-Action", "")
        if action in RECOVERY_ACTIONS:
            raise InferenceRecoveryError(action, status=response.status_code)


async def _check_async(response: httpx.Response) -> None:
    check_gateway_response(response)


def gateway_client(**kwargs) -> httpx.Client:
    return httpx.Client(
        auth=GatewayAuth(),
        event_hooks={"response": [check_gateway_response]},
        follow_redirects=False,
        **kwargs,
    )


def gateway_async_client(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        auth=GatewayAuth(),
        event_hooks={"response": [_check_async]},
        follow_redirects=False,
        **kwargs,
    )


def gateway_url(path: str) -> str:
    return settings.TOKENDANCE_BASE_URL.rstrip("/") + "/" + path.lstrip("/")


def gateway_model(model: str) -> str:
    return {
        "deepseek-flash": "deepseek-v4.1-flash",
        "doubao-seed-2-0-mini-260215": "seed-2.0-mini",
    }.get(model, model)
