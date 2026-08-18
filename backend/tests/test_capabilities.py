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


def test_summary_model_falls_back_to_primary_without_stepfun(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(llm_factory.settings, "STEPFUN_API_KEY", None)
    monkeypatch.setattr(llm_factory, "create_llm", lambda **kwargs: (sentinel, kwargs))

    model, kwargs = llm_factory.create_summary_llm()

    assert model is sentinel
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["disable_thinking"] is True
