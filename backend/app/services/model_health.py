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
    visible_speech_text,
)
from app.agents.reaction import (
    SpeechReactionPayload,
    build_reaction_analysis_prompt,
    build_reaction_system_prompt,
)
from app.core.config import settings
from app.core.llm_factory import create_summary_llm
from app.core.model_registry import MODEL_SPECS, ModelSpec

logger = logging.getLogger(__name__)

FIRST_TOKEN_PROBE_TIMEOUT_SECONDS = 15.0
FIRST_TOKEN_SLOW_THRESHOLD_SECONDS = 5.0
# This only bounds the lightweight health probe. Gameplay reactions retain
# their separate, much more generous production timeout.
REACTION_PROBE_TIMEOUT_SECONDS = 30.0
REACTION_SLOW_THRESHOLD_SECONDS = 12.0
CACHE_TTL_SECONDS = 30 * 60.0
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
_probe_task: asyncio.Task[list[dict[str, Any]]] | None = None
_probing_models: dict[str, dict[str, Any]] = {}


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
        "character_name_map": {"linlan": "林岚", "luming": "陆鸣"},
        "character_names": ["林岚", "陆鸣"],
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
                    text.strip() for text in visible_speech_text(data[0])
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


async def _probe_model(spec: ModelSpec) -> dict[str, Any]:
    """Probe speaking and reaction paths concurrently for one configured model."""
    first_token, reaction = await asyncio.gather(
        _measure_dimension(_measure_first_token, spec, FIRST_TOKEN_PROBE_TIMEOUT_SECONDS),
        _measure_dimension(_measure_reaction, spec, REACTION_PROBE_TIMEOUT_SECONDS),
        return_exceptions=True,
    )
    measurements = {"speech": first_token, "reaction": reaction}
    errors = [value for value in measurements.values() if isinstance(value, Exception)]
    unavailable = any(getattr(error, "status_code", None) in {401, 403} for error in errors)
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
        "unavailable"
        if unavailable
        else "timeout"
        if timeout_dimensions
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
    return {
        "model": spec.id,
        "status": status,
        "latency_ms": first_token_ms,
        "first_token_latency_ms": first_token_ms,
        "reaction_latency_ms": reaction if isinstance(reaction, int) else None,
        "slow_dimensions": slow_dimensions,
        "failed_dimensions": failed_dimensions,
        "timeout_dimensions": timeout_dimensions,
        "message": _health_message(status),
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def _probe_configured_models() -> list[dict[str, Any]]:
    global _cached_at_monotonic, _cached_models
    specs = [spec for spec in MODEL_SPECS if settings.get_api_key(spec.provider)]
    semaphore = asyncio.Semaphore(MODEL_PROBE_CONCURRENCY)

    async def probe(spec: ModelSpec) -> dict[str, Any]:
        async with semaphore:
            result = await _probe_model(spec)
            _probing_models[spec.id] = result
            return result

    models = list(await asyncio.gather(*(probe(spec) for spec in specs)))
    _cached_models = models
    _cached_at_monotonic = time.monotonic()
    return models


def _snapshot(*, probing: bool, cached: bool) -> dict[str, Any]:
    # Return remaining age so a browser cannot extend a nearly-expired server cache.
    remaining = max(0, math.ceil(CACHE_TTL_SECONDS - (time.monotonic() - _cached_at_monotonic)))
    return {
        "models": deepcopy(list(_probing_models.values()) if probing else (_cached_models or [])),
        "cached": cached,
        "probing": probing,
        "max_age_seconds": 0 if probing else remaining,
    }


async def get_model_health(
    *, force_refresh: bool = False, wait_for_completion: bool = True
) -> dict[str, Any]:
    """Share one process-wide run; HTTP callers receive progressive snapshots."""
    global _probe_task
    running = _probe_task is not None and not _probe_task.done()
    cache_is_fresh = (
        _cached_models is not None and time.monotonic() - _cached_at_monotonic < CACHE_TTL_SECONDS
    )
    if not running and cache_is_fresh and not force_refresh:
        return _snapshot(probing=False, cached=True)
    if not running:
        _probing_models.clear()
        _probe_task = asyncio.create_task(_probe_configured_models())
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
