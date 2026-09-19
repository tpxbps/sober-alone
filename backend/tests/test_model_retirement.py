from copy import deepcopy

import pytest

from app.agents.agent_manager import AgentManager
from app.core.config import settings
from app.core.llm_factory import create_llm
from app.services import model_health
from app.services.capabilities import get_capabilities


@pytest.mark.parametrize("backend", ["direct", "tokendance"])
@pytest.mark.asyncio
async def test_retired_chat_models_are_not_selectable_or_probed_but_tts_remains(
    monkeypatch, backend
):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", backend)
    monkeypatch.setattr(type(settings), "get_api_key", lambda *_: "configured")
    capabilities = get_capabilities()
    ids = {item["id"] for item in capabilities["models"]}
    assert not ids.intersection({"ling-3.0-flash", "mimo-v2.5", "doubao-seed-2-0-mini-260215"})
    assert "doubao-seed-2-0-lite-260215" in ids
    assert capabilities["features"]["static_tts"]["enabled"]
    for model in ("ling-3.0-flash", "mimo-v2.5"):
        with pytest.raises(ValueError, match="暂停服务"):
            create_llm(model)

    probed = []

    async def probe(spec):
        probed.append(spec.id)
        return {"model": spec.id}

    monkeypatch.setattr(model_health, "_probe_model", probe)
    model_health.clear_model_health_cache()
    try:
        await model_health.get_model_health(force_refresh=True)
        assert probed
        assert set(probed) <= ids
        assert "doubao-seed-2-0-lite-260215" in probed
    finally:
        model_health.clear_model_health_cache()


@pytest.mark.parametrize(
    ("old_provider", "old_model", "provider", "model"),
    [
        ("inclusionai", "ling-3.0-flash", "deepseek", "deepseek-flash"),
        ("mimo", "mimo-v2.5", "deepseek", "deepseek-flash"),
        ("stepfun", "step-3.5-flash", "deepseek", "deepseek-flash"),
        ("bytedance", "doubao-seed-2-0-mini-260215", "bytedance", "doubao-seed-2-0-lite-260215"),
        ("mimo", None, "deepseek", "deepseek-flash"),
    ],
)
@pytest.mark.asyncio
async def test_saved_games_resume_with_matching_model_and_provider(
    monkeypatch, old_provider, old_model, provider, model
):
    captured = []

    class Player:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    monkeypatch.setattr(
        type(settings), "get_api_key", lambda _, p: None if p == "zhipuai" else "key"
    )
    monkeypatch.setattr("app.agents.agent_manager.AgentPlayer", Player)
    monkeypatch.setattr("app.agents.agent_manager._game_checkpointer", lambda: None)
    saved = {"ai": {"provider": old_provider, "model": old_model}}
    original = deepcopy(saved)
    manager = AgentManager("resume-test", "sample")
    await manager.initialize_agents(
        [{"character_id": "human"}, {"character_id": "ai"}], "human", saved
    )
    assert saved == original
    assert manager.get_llm_info("ai") == {"provider": provider, "model": model}
    assert captured[0]["llm_provider"] == provider
    assert captured[0]["llm_model"] == model


def test_seed_legacy_alias_uses_lite_gateway_and_supported_thinking_parameter(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    llm = create_llm("doubao-seed-2-0-mini-260215", disable_thinking=True)
    assert llm.model_name == "seed-2.0-lite"
    assert llm.extra_body == {"thinking": {"type": "disabled"}}
