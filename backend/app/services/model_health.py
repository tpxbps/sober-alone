"""Cached dual-path health hints for selectable game models."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.reaction import (
    SpeechReactionPayload,
    build_reaction_analysis_prompt,
    build_reaction_system_prompt,
)
from app.core.config import settings
from app.core.llm_factory import create_llm
from app.core.model_registry import MODEL_SPECS, ModelSpec

logger = logging.getLogger(__name__)

FIRST_TOKEN_PROBE_TIMEOUT_SECONDS = 15.0
FIRST_TOKEN_SLOW_THRESHOLD_SECONDS = 5.0
# This only bounds the lightweight health probe. Gameplay reactions retain
# their separate, much more generous production timeout.
REACTION_PROBE_TIMEOUT_SECONDS = 30.0
REACTION_SLOW_THRESHOLD_SECONDS = 12.0
CACHE_TTL_SECONDS = 15 * 60.0
INCOMPLETE_CACHE_TTL_SECONDS = 90.0
MODEL_PROBE_CONCURRENCY = 4
TRANSIENT_PROBE_ATTEMPTS = 2

_REACTION_PROBE_ROLE = """你是旧广播站的档案管理员林岚。你谨慎、重视时间线，
只根据已公开发言和自己的经历更新判断。"""
_REACTION_PROBE_SCRIPT = """21:35 你检查过设备柜，R-07 录音笔当时仍在；
21:48 你再次经过时，设备柜门虚掩，但你没有看清是谁动过它。"""
_REACTION_PROBE_SPEAKER = "陆鸣"
_REACTION_PROBE_SPEECH = """我在21:26离开导播间，21:39回来时服务器已经停用。
陈朔说自己只做例行维护，却解释不了七分钟日志空白；而且R-07录音笔随后失踪。
林岚，你21:35见过录音笔，能否确认陈朔当时是否靠近设备柜？我认为他最可疑。"""

HealthDimension = Literal["speech", "reaction"]

_cached_models: list[dict[str, Any]] | None = None
_cached_at_monotonic = 0.0
_cached_ttl_seconds = CACHE_TTL_SECONDS
_probe_task: asyncio.Task[list[dict[str, Any]]] | None = None


def _chunk_text(chunk: Any) -> str:
    text = getattr(chunk, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    content = getattr(chunk, "content", "")
    return content.strip() if isinstance(content, str) else ""


def _safe_error_hint(exc: Exception) -> tuple[str, str]:
    status_code = getattr(exc, "status_code", None)
    if status_code in {401, 403}:
        return "unavailable", "该模型当前鉴权异常，请检查对应 API Key"
    return "slow", "该模型当前探测异常，响应可能较慢"


async def _measure_first_token(spec: ModelSpec) -> int:
    """Measure speaking-agent time to first visible token in milliseconds."""
    model = create_llm(
        model=spec.id,
        temperature=0,
        timeout=int(FIRST_TOKEN_PROBE_TIMEOUT_SECONDS),
        max_retries=0,
        disable_thinking=True,
    )
    messages = [
        SystemMessage(content="这是一次服务连通性检查。请严格遵循用户要求。"),
        HumanMessage(content="只回复一个字：好"),
    ]
    started_at = time.perf_counter()
    async with asyncio.timeout(FIRST_TOKEN_PROBE_TIMEOUT_SECONDS):
        async for chunk in model.astream(messages):
            if _chunk_text(chunk):
                return round((time.perf_counter() - started_at) * 1000)
    raise RuntimeError("empty model response")


async def _measure_reaction(spec: ModelSpec) -> int:
    """Measure a production-shaped structured reaction through validation."""
    model = create_llm(
        model=spec.id,
        temperature=0,
        timeout=int(REACTION_PROBE_TIMEOUT_SECONDS),
        max_retries=0,
        disable_thinking=True,
    )
    structured = model.with_structured_output(
        SpeechReactionPayload,
        method="json_schema",
    )
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
    SpeechReactionPayload.model_validate(result).to_reaction()
    return round((time.perf_counter() - started_at) * 1000)


async def _measure_with_transient_retry(
    measure: Callable[[ModelSpec], Awaitable[int]], spec: ModelSpec
) -> int:
    """Retry one transient probe failure without hiding auth failures."""

    last_error: Exception | None = None
    for attempt in range(TRANSIENT_PROBE_ATTEMPTS):
        try:
            return await measure(spec)
        except Exception as exc:  # noqa: BLE001 - provider exceptions are intentionally normalized
            if getattr(exc, "status_code", None) in {401, 403}:
                raise
            # A full probe timeout already consumed the entire dimension budget.
            # Let the UI report an incomplete sample and offer an explicit retry.
            if isinstance(exc, TimeoutError):
                raise
            last_error = exc
            if attempt + 1 < TRANSIENT_PROBE_ATTEMPTS:
                await asyncio.sleep(0.25)
    assert last_error is not None
    raise last_error


def _dimension_is_slow(value: int | Exception, threshold_seconds: float) -> bool:
    return isinstance(value, int) and value > threshold_seconds * 1000


def _health_message(
    status: str,
    slow_dimensions: list[HealthDimension],
    failed_dimensions: list[HealthDimension],
) -> str:
    if status == "unavailable":
        return "该模型当前鉴权异常，请检查对应 API Key"
    if status == "unknown":
        if failed_dimensions == ["reaction"]:
            return "本次反应测速未完成，可稍后重新测速"
        if failed_dimensions == ["speech"]:
            return "本次发言测速未完成，可稍后重新测速"
        return "本次模型测速未完成，可能受网络波动影响"
    if slow_dimensions == ["reaction"]:
        return "该模型当前反应分析稍慢，可能影响每轮讨论节奏"
    if slow_dimensions == ["speech"]:
        return "该模型当前发言响应稍慢"
    if slow_dimensions:
        return "该模型当前发言与反应分析均稍慢，可能影响讨论节奏"
    return "响应正常"


async def _probe_model(spec: ModelSpec) -> dict[str, Any]:
    """Probe speaking and reaction paths concurrently for one configured model."""
    checked_at = datetime.now(UTC).isoformat()
    first_token, reaction = await asyncio.gather(
        _measure_with_transient_retry(_measure_first_token, spec),
        _measure_with_transient_retry(_measure_reaction, spec),
        return_exceptions=True,
    )
    errors = [value for value in (first_token, reaction) if isinstance(value, Exception)]
    unavailable = any(getattr(error, "status_code", None) in {401, 403} for error in errors)
    failed_dimensions: list[HealthDimension] = []
    if isinstance(first_token, Exception):
        failed_dimensions.append("speech")
    if isinstance(reaction, Exception):
        failed_dimensions.append("reaction")
    slow_dimensions: list[HealthDimension] = []
    if _dimension_is_slow(first_token, FIRST_TOKEN_SLOW_THRESHOLD_SECONDS):
        slow_dimensions.append("speech")
    if _dimension_is_slow(reaction, REACTION_SLOW_THRESHOLD_SECONDS):
        slow_dimensions.append("reaction")
    status = (
        "unavailable"
        if unavailable
        else "unknown"
        if failed_dimensions
        else "slow"
        if slow_dimensions
        else "normal"
    )

    for error in errors:
        logger.info(
            "Model health probe failed model=%s error=%s status=%s",
            spec.id,
            type(error).__name__,
            getattr(error, "status_code", None),
        )

    first_token_ms = first_token if isinstance(first_token, int) else None
    reaction_ms = reaction if isinstance(reaction, int) else None
    return {
        "model": spec.id,
        "status": status,
        # Backward-compatible alias retained for existing clients.
        "latency_ms": first_token_ms,
        "first_token_latency_ms": first_token_ms,
        "reaction_latency_ms": reaction_ms,
        "slow_dimensions": slow_dimensions,
        "failed_dimensions": failed_dimensions,
        "message": _health_message(status, slow_dimensions, failed_dimensions),
        "checked_at": checked_at,
    }


async def _probe_configured_models() -> list[dict[str, Any]]:
    global _cached_at_monotonic, _cached_models, _cached_ttl_seconds

    specs = [spec for spec in MODEL_SPECS if settings.get_api_key(spec.provider)]
    semaphore = asyncio.Semaphore(MODEL_PROBE_CONCURRENCY)

    async def probe(spec: ModelSpec) -> dict[str, Any]:
        async with semaphore:
            return await _probe_model(spec)

    models = list(await asyncio.gather(*(probe(spec) for spec in specs)))
    _cached_models = models
    _cached_at_monotonic = time.monotonic()
    _cached_ttl_seconds = (
        INCOMPLETE_CACHE_TTL_SECONDS
        if any(item["status"] == "unknown" for item in models)
        else CACHE_TTL_SECONDS
    )
    return models


async def get_model_health(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return cached health hints, sharing one probe run across concurrent callers."""
    global _probe_task

    cache_is_fresh = (
        _cached_models is not None
        and time.monotonic() - _cached_at_monotonic < _cached_ttl_seconds
    )
    if cache_is_fresh and not force_refresh:
        return {
            "models": deepcopy(_cached_models),
            "cached": True,
            "max_age_seconds": round(_cached_ttl_seconds),
        }

    if _probe_task is None or _probe_task.done():
        _probe_task = asyncio.create_task(_probe_configured_models())
    task = _probe_task
    try:
        models = await asyncio.shield(task)
    finally:
        if task.done() and _probe_task is task:
            _probe_task = None
    return {
        "models": deepcopy(models),
        "cached": False,
        "max_age_seconds": round(_cached_ttl_seconds),
    }


def clear_model_health_cache() -> None:
    """Reset process-local probe state. Intended for tests and explicit refreshes."""
    global _cached_at_monotonic, _cached_models, _cached_ttl_seconds, _probe_task
    if _probe_task is not None and not _probe_task.done():
        _probe_task.cancel()
    _probe_task = None
    _cached_models = None
    _cached_at_monotonic = 0.0
    _cached_ttl_seconds = CACHE_TTL_SECONDS
