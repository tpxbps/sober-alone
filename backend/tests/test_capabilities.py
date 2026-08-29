from app.core import llm_factory
from app.services import capabilities


def _clear_keys(monkeypatch):
    for name in (
        "DEEPSEEK_API_KEY",
        "STEPFUN_API_KEY",
        "QWEN_API_KEY",
        "DOUBAO_API_KEY",
        "ZHIPUAI_API_KEY",
        "MIMO_API_KEY",
        "HUNYUAN_API_KEY",
    ):
        monkeypatch.setattr(capabilities.settings, name, None)


def test_capabilities_never_expose_keys(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setattr(capabilities.settings, "DEEPSEEK_API_KEY", "secret-deepseek-value")

    result = capabilities.get_capabilities()

    assert result["mode"] == "local-first-single-user-single-process"
    assert next(model for model in result["models"] if model["provider"] == "deepseek")[
        "configured"
    ]
    assert "secret-deepseek-value" not in repr(result)
    assert not result["features"]["rag"]["enabled"]
    assert "完整个人剧本" in result["features"]["rag"]["reason"]


def test_optional_capability_matrix(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setattr(capabilities.settings, "ZHIPUAI_API_KEY", "z")
    monkeypatch.setattr(capabilities.settings, "DOUBAO_API_KEY", "d")
    monkeypatch.setattr(capabilities.settings, "MIMO_API_KEY", "m")
    monkeypatch.setattr(capabilities.settings, "STEPFUN_API_KEY", "s")

    features = capabilities.get_capabilities()["features"]

    assert all(item["enabled"] for item in features.values())


def test_model_registry_keeps_configured_models_available_during_slow_periods(monkeypatch):
    _clear_keys(monkeypatch)
    monkeypatch.setattr(capabilities.settings, "HUNYUAN_API_KEY", "h")
    monkeypatch.setattr(capabilities.settings, "ZHIPUAI_API_KEY", "z")

    models = {item["id"]: item for item in capabilities.get_capabilities()["models"]}

    assert "qwen3.5-flash-2026-02-23" not in models
    assert {"qwen3.8-flash", "mimo-v2.5"} <= models.keys()
    assert models["hy3"]["configured"] is True
    assert models["glm-5.3-flash"]["configured"] is True


def test_summary_model_falls_back_to_primary_without_stepfun(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(llm_factory.settings, "STEPFUN_API_KEY", None)
    monkeypatch.setattr(llm_factory, "create_llm", lambda **kwargs: (sentinel, kwargs))

    model, kwargs = llm_factory.create_summary_llm()

    assert model is sentinel
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["disable_thinking"] is True


def test_openai_compatible_providers_do_not_receive_deepseek_specific_parameters(monkeypatch):
    captured = []

    def fake_openai(model, _key, _base_url, _temperature, _timeout, _retries, extra_body=None):
        captured.append((model, extra_body))
        return object()

    monkeypatch.setattr(llm_factory, "_create_openai_compatible", fake_openai)
    monkeypatch.setattr(llm_factory.settings, "QWEN_API_KEY", "q")
    monkeypatch.setattr(llm_factory.settings, "MIMO_API_KEY", "m")
    monkeypatch.setattr(llm_factory.settings, "ZHIPUAI_API_KEY", "z")
    monkeypatch.setattr(llm_factory.settings, "HUNYUAN_API_KEY", "h")

    for model in ("qwen3.8-flash", "mimo-v2.5", "hy3", "glm-5.3-flash"):
        llm_factory.create_llm(model=model, disable_thinking=True)

    assert captured == [
        ("qwen3.8-flash", {"enable_thinking": False}),
        ("mimo-v2.5", None),
        ("hy3", None),
        ("glm-5.3-flash", None),
    ]
