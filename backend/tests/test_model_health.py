import asyncio

import pytest

from app.core.model_registry import ModelSpec
from app.services import model_health


@pytest.fixture(autouse=True)
def _reset_model_health_cache():
    model_health.clear_model_health_cache()
    yield
    model_health.clear_model_health_cache()


def _spec() -> ModelSpec:
    return ModelSpec("glm-5.3-flash", "glm-5.3-flash", "zhipuai", "Zhipu GLM")


@pytest.mark.asyncio
async def test_probe_marks_slow_when_only_structured_reaction_exceeds_threshold(
    monkeypatch,
):
    async def first_token(_spec):
        return 900

    async def reaction(_spec):
        return 18_500

    monkeypatch.setattr(model_health, "_measure_first_token", first_token)
    monkeypatch.setattr(model_health, "_measure_reaction", reaction)

    result = await model_health._probe_model(_spec())

    assert result["status"] == "slow"
    assert result["latency_ms"] == 900
    assert result["first_token_latency_ms"] == 900
    assert result["reaction_latency_ms"] == 18_500
    assert result["slow_dimensions"] == ["reaction"]
    assert result["failed_dimensions"] == []
    assert result["message"] == "该模型当前反应分析稍慢，可能影响每轮讨论节奏"


@pytest.mark.asyncio
async def test_probe_marks_both_dimensions_and_does_not_expose_model_output(monkeypatch):
    async def first_token(_spec):
        return 6_100

    async def reaction(_spec):
        return 13_200

    monkeypatch.setattr(model_health, "_measure_first_token", first_token)
    monkeypatch.setattr(model_health, "_measure_reaction", reaction)

    result = await model_health._probe_model(_spec())

    assert result["status"] == "slow"
    assert result["slow_dimensions"] == ["speech", "reaction"]
    assert result["message"] == "该模型当前发言与反应分析均稍慢，可能影响讨论节奏"
    assert "response" not in result


@pytest.mark.asyncio
async def test_reaction_probe_failure_is_incomplete_instead_of_a_slow_false_positive(
    monkeypatch,
):
    async def first_token(_spec):
        return 500

    async def reaction(_spec):
        raise TimeoutError

    monkeypatch.setattr(model_health, "_measure_first_token", first_token)
    monkeypatch.setattr(model_health, "_measure_reaction", reaction)

    result = await model_health._probe_model(_spec())

    assert result["status"] == "unknown"
    assert result["first_token_latency_ms"] == 500
    assert result["reaction_latency_ms"] is None
    assert result["slow_dimensions"] == []
    assert result["failed_dimensions"] == ["reaction"]
    assert result["message"] == "本次反应测速未完成，可稍后重新测速"


@pytest.mark.asyncio
async def test_transient_probe_failure_retries_once(monkeypatch):
    calls = 0

    async def flaky_measure(_spec):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary connection reset")
        return 700

    assert await model_health._measure_with_transient_retry(flaky_measure, _spec()) == 700
    assert calls == 2


@pytest.mark.asyncio
async def test_health_probe_is_parallel_singleflight_and_cached(monkeypatch):
    specs = (
        ModelSpec("hy3", "hy3", "hunyuan", "Tencent Hunyuan"),
        _spec(),
    )
    calls: list[str] = []

    async def fake_probe(spec):
        calls.append(spec.id)
        await asyncio.sleep(0)
        return {
            "model": spec.id,
            "status": "normal",
            "latency_ms": 100,
            "first_token_latency_ms": 100,
            "reaction_latency_ms": 800,
            "slow_dimensions": [],
            "failed_dimensions": [],
            "message": "响应正常",
            "checked_at": "2026-08-28T00:00:00+00:00",
        }

    monkeypatch.setattr(model_health, "MODEL_SPECS", specs)
    monkeypatch.setattr(
        type(model_health.settings), "get_api_key", lambda _settings, _provider: "key"
    )
    monkeypatch.setattr(model_health, "_probe_model", fake_probe)

    first, concurrent = await asyncio.gather(
        model_health.get_model_health(), model_health.get_model_health()
    )
    cached = await model_health.get_model_health()

    assert sorted(calls) == ["glm-5.3-flash", "hy3"]
    assert first["models"] == concurrent["models"] == cached["models"]
    assert first["cached"] is False
    assert cached["cached"] is True
    assert cached["max_age_seconds"] == model_health.CACHE_TTL_SECONDS


@pytest.mark.asyncio
async def test_force_refresh_bypasses_a_fresh_cache(monkeypatch):
    calls = 0

    async def fake_configured_models():
        nonlocal calls
        calls += 1
        model_health._cached_models = []
        model_health._cached_at_monotonic = model_health.time.monotonic()
        return []

    monkeypatch.setattr(model_health, "_probe_configured_models", fake_configured_models)

    await model_health.get_model_health()
    cached = await model_health.get_model_health()
    refreshed = await model_health.get_model_health(force_refresh=True)

    assert calls == 2
    assert cached["cached"] is True
    assert refreshed["cached"] is False


def test_provider_errors_are_safe_user_facing_hints():
    class UnauthorizedError(Exception):
        status_code = 401

    assert model_health._safe_error_hint(UnauthorizedError("secret details")) == (
        "unavailable",
        "该模型当前鉴权异常，请检查对应 API Key",
    )
    assert model_health._safe_error_hint(RuntimeError("endpoint exploded")) == (
        "slow",
        "该模型当前探测异常，响应可能较慢",
    )
