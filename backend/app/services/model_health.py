"""Cached dual-path health hints for selectable game models."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal

from httpx import TimeoutException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from openai import APIConnectionError, APITimeoutError

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.game_model_paths import (
    bind_reaction_output,
    build_role_agent,
    create_game_model,
    visible_role_speech_text,
)
from app.agents.reaction import (
    SpeechReactionPayload,
    build_reaction_analysis_prompt,
    build_reaction_system_prompt,
)
from app.core.config import settings
from app.core.inference import InferenceRecoveryError, raise_for_inference_recovery
from app.core.llm_factory import create_summary_llm
from app.core.model_registry import MODEL_SPECS, ModelSpec

logger = logging.getLogger(__name__)

FIRST_TOKEN_PROBE_TIMEOUT_SECONDS = 15.0
FIRST_TOKEN_SLOW_THRESHOLD_SECONDS = 10.0
# This only bounds the lightweight health probe. Gameplay reactions retain
# their separate, much more generous production timeout.
REACTION_PROBE_TIMEOUT_SECONDS = 30.0
REACTION_SLOW_THRESHOLD_SECONDS = 12.0
CACHE_TTL_SECONDS = 30 * 60.0
FAILURE_CACHE_TTL_SECONDS = 30.0
MODEL_PROBE_CONCURRENCY = 4
TRANSIENT_PROBE_ATTEMPTS = 2

_REACTION_PROBE_ROLE = """你是研究站的值班记录员林岚。你谨慎、重视时间线，
只根据已公开发言和自己的经历更新判断。"""
_REACTION_PROBE_SCRIPT = """21:35 你检查过设备柜，K-12 记录仪当时仍在；
21:48 你再次经过时，设备柜门虚掩，但你没有看清是谁动过它。"""
_REACTION_PROBE_SPEAKER = "赵屿"
_REACTION_PROBE_SPEECH = """我在21:26离开工作间，21:39回来时服务器已经停用。
程宇说自己只做例行维护，却解释不了七分钟日志空白；而且K-12记录仪随后失踪。
林岚，你21:35见过记录仪，能否确认程宇当时是否靠近设备柜？我认为他最可疑。"""

HealthDimension = Literal["speech", "reaction"]

_cached_models: list[dict[str, Any]] | None = None
_cached_at_monotonic = 0.0
_probe_task: asyncio.Task[list[dict[str, Any]]] | None = None
_probing_models: dict[str, dict[str, Any]] = {}
_successful_models: dict[str, tuple[float, dict[str, Any]]] = {}


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, (TimeoutError, APITimeoutError, TimeoutException)) or getattr(
        exc, "status_code", None
    ) in {408, 504}


async def _measure_first_token(spec: ModelSpec) -> int:
    """Measure speaking-agent time to first visible token in milliseconds."""
    model = create_game_model(
        spec.id,
        "speech",
        timeout=int(FIRST_TOKEN_PROBE_TIMEOUT_SECONDS),
        max_retries=0,
    )
    try:
        summary_model = create_summary_llm()
    except Exception:
        summary_model = model
    agent = build_role_agent(
        model,
        summary_model,
        system_prompt=build_role_system_prompt(_REACTION_PROBE_ROLE, _REACTION_PROBE_SCRIPT, False),
        rag_enabled=False,
        checkpointer=InMemorySaver(),
        middleware=[],
    )
    state = {
        "messages": [
            HumanMessage(
                content="【当前阶段：自我介绍】用两三句话介绍你的身份和21:35看到的情况，不要透露未公开的秘密。"
            )
        ],
        "session_id": "model-health",
        "script_id": "model-health",
        "character_id": "linlan",
        "character_name": "林岚",
        "current_stage": "intro",
        "current_round": 0,
        "character_name_map": {"linlan": "林岚", "zhaoyu": "赵屿"},
        "character_names": ["林岚", "赵屿"],
        "public_clues": [],
    }
    started_at = time.perf_counter()
    async with asyncio.timeout(FIRST_TOKEN_PROBE_TIMEOUT_SECONDS):
        stream = agent.astream(
            state, {"configurable": {"thread_id": "probe"}}, stream_mode=["messages", "custom"]
        )
        async with aclosing(stream):
            async for mode, data in stream:
                if mode == "messages" and any(
                    text.strip() for text in visible_role_speech_text(*data)
                ):
                    return round((time.perf_counter() - started_at) * 1000)
    raise RuntimeError("empty model response")


async def _measure_reaction(spec: ModelSpec) -> int:
    """Measure a production-shaped structured reaction through validation."""
    model = create_game_model(
        spec.id,
        "reaction",
        timeout=int(REACTION_PROBE_TIMEOUT_SECONDS),
        max_retries=0,
    )
    structured = bind_reaction_output(model, spec.id)
    messages = [
        SystemMessage(
            content=build_reaction_system_prompt(
                _REACTION_PROBE_ROLE,
                _REACTION_PROBE_SCRIPT,
            )
        ),
        HumanMessage(
            content=build_reaction_analysis_prompt(
                "林岚",
                _REACTION_PROBE_SPEAKER,
                _REACTION_PROBE_SPEECH,
            )
        ),
    ]
    started_at = time.perf_counter()
    async with asyncio.timeout(REACTION_PROBE_TIMEOUT_SECONDS):
        result = await structured.ainvoke(messages)
    reaction = SpeechReactionPayload.model_validate(result).to_reaction()
    if not reaction.main_perspective.strip():
        raise ValueError("empty reaction analysis")
    return round((time.perf_counter() - started_at) * 1000)


async def _measure_with_transient_retry(
    measure: Callable[[ModelSpec], Awaitable[int]], spec: ModelSpec
) -> int:
    """Retry a connection/server failure once; timeouts and invalid output are final."""
    for attempt in range(TRANSIENT_PROBE_ATTEMPTS):
        try:
            return await measure(spec)
        except Exception as exc:  # noqa: BLE001 - normalize provider failures
            # SDK transport wrappers must not hide account/configuration failures
            # or turn them into repeated billable connection retries.
            raise_for_inference_recovery(exc)
            status = getattr(exc, "status_code", None)
            transient = isinstance(exc, (APIConnectionError, ConnectionError)) or (
                isinstance(status, int) and 500 <= status < 600
            )
            if _is_timeout(exc) or not transient or attempt + 1 == TRANSIENT_PROBE_ATTEMPTS:
                raise
            await asyncio.sleep(0.25)
    raise AssertionError("Probe attempts exhausted")


async def _measure_dimension(
    measure: Callable[[ModelSpec], Awaitable[int]], spec: ModelSpec, budget_seconds: float
) -> int:
    # Retries share the dimension deadline instead of doubling its total budget.
    async with asyncio.timeout(budget_seconds):
        return await _measure_with_transient_retry(measure, spec)


def _dimension_is_slow(value: int | Exception, threshold_seconds: float) -> bool:
    return isinstance(value, int) and value > threshold_seconds * 1000


def _health_message(status: str) -> str:
    return {
        "unavailable": "模型暂不可用，请选择其他模型",
        "timeout": "测速超时，请稍后重试",
        "unknown": "测速失败，请重试",
        "slow": "响应较慢",
    }.get(status, "响应正常")


def _probe_error_code(error: Exception) -> str:
    if isinstance(error, InferenceRecoveryError):
        return "probe_auth" if error.status in {401, 403} else "probe_account"
    if getattr(error, "status_code", None) in {401, 403}:
        return "probe_auth"
    return "probe_failed"


async def _probe_model(spec: ModelSpec) -> dict[str, Any]:
    """Probe speaking and reaction paths concurrently for one configured model."""
    if spec.tier == "frontier":
        raise ValueError("Frontier models do not participate in health probes")
    first_token, reaction = await asyncio.gather(
        _measure_dimension(_measure_first_token, spec, FIRST_TOKEN_PROBE_TIMEOUT_SECONDS),
        _measure_dimension(_measure_reaction, spec, REACTION_PROBE_TIMEOUT_SECONDS),
        return_exceptions=True,
    )
    measurements = {"speech": first_token, "reaction": reaction}
    errors = [value for value in measurements.values() if isinstance(value, Exception)]
    error_codes = {_probe_error_code(error) for error in errors}
    service_error = next(
        (code for code in ("probe_auth", "probe_account") if code in error_codes), None
    )
    failed_dimensions = [dim for dim, value in measurements.items() if isinstance(value, Exception)]
    timeout_dimensions = [
        dim
        for dim, value in measurements.items()
        if isinstance(value, Exception) and _is_timeout(value)
    ]
    slow_dimensions: list[HealthDimension] = []
    if _dimension_is_slow(first_token, FIRST_TOKEN_SLOW_THRESHOLD_SECONDS):
        slow_dimensions.append("speech")
    if _dimension_is_slow(reaction, REACTION_SLOW_THRESHOLD_SECONDS):
        slow_dimensions.append("reaction")
    status = (
        "unknown"
        if service_error
        else "timeout"
        if timeout_dimensions
        else "unknown"
        if failed_dimensions
        else "slow"
        if slow_dimensions
        else "normal"
    )
    for error in errors:
        logger.warning(
            "Model health probe failed model=%s error=%s status=%s code=%s",
            spec.id,
            type(error).__name__,
            getattr(error, "status_code", getattr(error, "status", None)),
            _probe_error_code(error),
        )
    first_token_ms = first_token if isinstance(first_token, int) else None
    return {
        "model": spec.id,
        "status": status,
        "latency_ms": first_token_ms,
        "first_token_latency_ms": first_token_ms,
        "reaction_latency_ms": reaction if isinstance(reaction, int) else None,
        "slow_dimensions": slow_dimensions,
        "failed_dimensions": failed_dimensions,
        "timeout_dimensions": timeout_dimensions,
        "message": (
            "测速服务鉴权失败，暂无法判断模型状态"
            if service_error == "probe_auth"
            else "测速服务账户暂不可用，暂无法判断模型状态"
            if service_error == "probe_account"
            else _health_message(status)
        ),
        "error_code": service_error,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def _probe_configured_models(*, refresh_successful: bool = False) -> list[dict[str, Any]]:
    global _cached_at_monotonic, _cached_models
    specs = [
        spec
        for spec in MODEL_SPECS
        if spec.tier != "frontier"
        and settings.is_model_enabled(spec.id)
        and settings.get_api_key(spec.provider)
    ]
    semaphore = asyncio.Semaphore(MODEL_PROBE_CONCURRENCY)

    async def probe(spec: ModelSpec) -> dict[str, Any]:
        async with semaphore:
            previous = _successful_models.get(spec.id)
            if (
                not refresh_successful
                and previous
                and time.monotonic() - previous[0] < CACHE_TTL_SECONDS
            ):
                _probing_models[spec.id] = previous[1]
                return previous[1]
            result = await _probe_model(spec)
            if result.get("status") in {"normal", "slow"}:
                _successful_models[spec.id] = (time.monotonic(), result)
            else:
                _successful_models.pop(spec.id, None)
            _probing_models[spec.id] = result
            return result

    models = list(await asyncio.gather(*(probe(spec) for spec in specs)))
    _cached_models = models
    _cached_at_monotonic = time.monotonic()
    return models


def _cache_ttl() -> float:
    batch_ttl = (
        FAILURE_CACHE_TTL_SECONDS
        if any(item.get("status") not in {"normal", "slow"} for item in (_cached_models or []))
        else CACHE_TTL_SECONDS
    )
    # Reusing a successful sample must never renew its original expiry.
    return max(
        0.0,
        min(
            [batch_ttl]
            + [
                _successful_models[item["model"]][0] + CACHE_TTL_SECONDS - _cached_at_monotonic
                for item in (_cached_models or [])
                if item["model"] in _successful_models
            ]
        ),
    )


def _snapshot(*, probing: bool, cached: bool, retry_after_seconds: int = 0) -> dict[str, Any]:
    # Return remaining age so a browser cannot extend a nearly-expired server cache.
    remaining = max(0, math.ceil(_cache_ttl() - (time.monotonic() - _cached_at_monotonic)))
    models = deepcopy(list(_probing_models.values()) if probing else (_cached_models or []))
    service_errors = {item.get("error_code") for item in models}
    service_error = next(
        (code for code in ("probe_auth", "probe_account") if code in service_errors), None
    )
    return {
        "models": models,
        "cached": cached,
        "probing": probing,
        "max_age_seconds": 0 if probing else remaining,
        "retry_after_seconds": retry_after_seconds,
        "service_error": service_error,
    }


async def get_model_health(
    *,
    force_refresh: bool = False,
    wait_for_completion: bool = True,
    refresh_cooldown_seconds: float = 0,
) -> dict[str, Any]:
    """Share one process-wide run; HTTP callers receive progressive snapshots."""
    global _probe_task
    running = _probe_task is not None and not _probe_task.done()
    cache_is_fresh = (
        _cached_models is not None and time.monotonic() - _cached_at_monotonic < _cache_ttl()
    )
    if not running and force_refresh and cache_is_fresh:
        retry_after = math.ceil(
            refresh_cooldown_seconds - (time.monotonic() - _cached_at_monotonic)
        )
        if retry_after > 0:
            return _snapshot(probing=False, cached=True, retry_after_seconds=retry_after)
    if not running and cache_is_fresh and not force_refresh:
        return _snapshot(probing=False, cached=True)
    if not running:
        _probing_models.clear()
        # Retest failures first. A single failed model must not repeatedly spend
        # the successful models' probe budget while their samples remain valid.
        refresh_successful = force_refresh and all(
            item.get("status") in {"normal", "slow"} for item in (_cached_models or [])
        )
        _probe_task = asyncio.create_task(
            _probe_configured_models(refresh_successful=refresh_successful)
        )
    if not wait_for_completion:
        return _snapshot(probing=True, cached=False)
    await asyncio.shield(_probe_task)
    return _snapshot(probing=False, cached=False)


def clear_model_health_cache() -> None:
    """Reset process-local state for tests."""
    global _cached_at_monotonic, _cached_models, _probe_task
    if _probe_task is not None and not _probe_task.done():
        _probe_task.cancel()
    _probe_task = None
    _cached_models = None
    _cached_at_monotonic = 0.0
    _probing_models.clear()
    _successful_models.clear()
