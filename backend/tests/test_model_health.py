import asyncio

import httpx
import pytest
from openai import APITimeoutError

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
    assert result["message"] == "响应较慢"


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
    assert result["message"] == "响应较慢"
    assert "response" not in result


@pytest.mark.asyncio
async def test_reaction_timeout_is_explicit_and_keeps_successful_speech_sample(
    monkeypatch,
):
    async def first_token(_spec):
        return 500

    async def reaction(_spec):
        raise TimeoutError

    monkeypatch.setattr(model_health, "_measure_first_token", first_token)
    monkeypatch.setattr(model_health, "_measure_reaction", reaction)

    result = await model_health._probe_model(_spec())

    assert result["status"] == "timeout"
    assert result["first_token_latency_ms"] == 500
    assert result["reaction_latency_ms"] is None
    assert result["slow_dimensions"] == []
    assert result["failed_dimensions"] == ["reaction"]
    assert result["timeout_dimensions"] == ["reaction"]
    assert "测速超时，请稍后重试" in result["message"]
    assert "网络" not in result["message"]


@pytest.mark.asyncio
async def test_transient_probe_failure_retries_once(monkeypatch):
    calls = 0

    async def flaky_measure(_spec):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("temporary connection reset")
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TimeoutError(),
        httpx.ReadTimeout("private"),
        APITimeoutError(request=httpx.Request("POST", "https://provider.invalid")),
    ],
)
async def test_all_timeout_types_are_final_without_retry(monkeypatch, error):
    calls = 0

    async def measure(_spec):
        nonlocal calls
        calls += 1
        raise error

    with pytest.raises(type(error)):
        await model_health._measure_with_transient_retry(measure, _spec())
    assert calls == 1
    monkeypatch.setattr(model_health, "_measure_reaction", measure)

    async def speech(_spec):
        return 50

    monkeypatch.setattr(model_health, "_measure_first_token", speech)
    result = await model_health._probe_model(_spec())
    assert result["status"] == "timeout"
    assert "private" not in result["message"]


@pytest.mark.asyncio
async def test_non_timeout_failure_does_not_claim_timeout_or_network_cause(monkeypatch):
    async def broken(_spec):
        raise ValueError("secret provider output")

    monkeypatch.setattr(model_health, "_measure_first_token", broken)
    monkeypatch.setattr(model_health, "_measure_reaction", broken)
    result = await model_health._probe_model(_spec())
    assert result["status"] == "unknown"
    assert result["timeout_dimensions"] == []
    assert "测速失败" in result["message"]
    assert "secret" not in repr(result)
    assert "网络" not in result["message"]


@pytest.mark.asyncio
async def test_partial_results_are_available_while_slow_model_is_running(monkeypatch):
    release = asyncio.Event()
    fast_ready = asyncio.Event()
    calls = []

    async def fake_probe(spec):
        calls.append(spec.id)
        if spec.id == "glm-5.3-flash":
            await release.wait()
        else:
            fast_ready.set()
        return {"model": spec.id, "status": "normal"}

    monkeypatch.setattr(
        model_health, "MODEL_SPECS", (ModelSpec("hy3", "hy3", "hunyuan", "Tencent"), _spec())
    )
    monkeypatch.setattr(type(model_health.settings), "get_api_key", lambda *_: "key")
    monkeypatch.setattr(model_health, "_probe_model", fake_probe)
    initial = await model_health.get_model_health(wait_for_completion=False)
    assert initial["probing"] and initial["models"] == []
    await fast_ready.wait()
    partial = await model_health.get_model_health(wait_for_completion=False, force_refresh=True)
    assert partial["probing"] and partial["max_age_seconds"] == 0
    assert partial["models"] == [{"model": "hy3", "status": "normal"}]
    assert len(calls) == 2
    release.set()
    complete = await model_health.get_model_health()
    assert not complete["probing"] and len(complete["models"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["normal", "timeout", "unknown"])
async def test_all_results_are_cached_for_30_minutes_with_remaining_age(monkeypatch, status):
    now = [100.0]
    monkeypatch.setattr(model_health.time, "monotonic", lambda: now[0])
    calls = []

    async def fake_probe(spec):
        calls.append(spec.id)
        return {"model": spec.id, "status": status}

    monkeypatch.setattr(model_health, "MODEL_SPECS", (_spec(),))
    monkeypatch.setattr(type(model_health.settings), "get_api_key", lambda *_: "key")
    monkeypatch.setattr(model_health, "_probe_model", fake_probe)
    await model_health.get_model_health()
    now[0] += 1799
    cached = await model_health.get_model_health()
    assert cached["cached"] and cached["max_age_seconds"] == 1
    assert len(calls) == 1
    now[0] += 1
    assert not (await model_health.get_model_health())["cached"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_cancel_shared_probe(monkeypatch):
    ready, release = asyncio.Event(), asyncio.Event()

    async def fake_probe(_spec):
        ready.set()
        await release.wait()
        return {"model": "glm-5.3-flash", "status": "normal"}

    monkeypatch.setattr(model_health, "MODEL_SPECS", (_spec(),))
    monkeypatch.setattr(type(model_health.settings), "get_api_key", lambda *_: "key")
    monkeypatch.setattr(model_health, "_probe_model", fake_probe)
    caller = asyncio.create_task(model_health.get_model_health())
    await ready.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    release.set()
    assert (await model_health.get_model_health())["models"][0]["status"] == "normal"


@pytest.mark.asyncio
async def test_speech_probe_uses_role_agent_and_closes_on_first_visible_token(monkeypatch):
    from langchain.messages import AIMessageChunk

    captured = {}
    model = object()

    def create_model(model_id, purpose, **kwargs):
        captured.update(model=model_id, purpose=purpose, options=kwargs)
        return model

    class Agent:
        async def astream(self, state, config, **kwargs):
            captured["state"] = state
            captured["stream_mode"] = kwargs["stream_mode"]
            try:
                yield "custom", "tool progress is not a speech token"
                yield (
                    "messages",
                    (
                        AIMessageChunk(
                            content="",
                            tool_call_chunks=[
                                {
                                    "name": "recall_public_clues",
                                    "args": "{}",
                                    "id": "test",
                                    "index": 0,
                                }
                            ],
                        ),
                        {},
                    ),
                )
                yield "messages", (AIMessageChunk(content="我是林岚。"), {})
                raise AssertionError("probe should close after the first visible text")
            finally:
                captured["closed"] = True

    def build_agent(speech_model, summary_model, **kwargs):
        assert speech_model is summary_model is model
        captured["agent_options"] = kwargs
        return Agent()

    def missing_summary():
        raise ValueError("optional provider is absent")

    monkeypatch.setattr(model_health, "create_game_model", create_model)
    monkeypatch.setattr(model_health, "create_summary_llm", missing_summary)
    monkeypatch.setattr(model_health, "build_role_agent", build_agent)
    assert await model_health._measure_first_token(_spec()) >= 0
    assert captured["purpose"] == "speech"
    assert captured["state"]["current_stage"] == "intro"
    assert captured["stream_mode"] == ["messages", "custom"]
    assert captured["closed"]


@pytest.mark.asyncio
async def test_empty_structured_response_cannot_be_a_normal_health_sample(monkeypatch):
    from app.agents.reaction import SpeechReactionPayload

    class Chain:
        async def ainvoke(self, _messages):
            return SpeechReactionPayload()

    monkeypatch.setattr(model_health, "create_game_model", lambda *args, **kwargs: object())
    monkeypatch.setattr(model_health, "bind_reaction_output", lambda *args: Chain())
    with pytest.raises(ValueError, match="empty reaction analysis"):
        await model_health._measure_reaction(_spec())
