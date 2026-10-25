import pytest
from langchain_core.messages import HumanMessage

from app.agents.game_model_paths import bind_reaction_output, create_game_model
from app.core.config import settings
from app.core.llm_factory import create_llm
from app.core.model_registry import get_model_spec
from app.core.reasoning_chat import ReasoningChatOpenAI
from app.services.capabilities import get_capabilities


@pytest.mark.parametrize(
    "model_id",
    [
        "deepseek-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
        "deepseek-v4.1-flash",
        "deepseek-v4.1-flash-1017",
    ],
)
def test_deepseek_saved_ids_dispatch_to_1017(monkeypatch, model_id):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    assert get_model_spec(model_id).id == "deepseek-flash"
    assert get_model_spec(model_id).name == "deepseek-v4.1-flash"
    assert create_llm(model_id).model_name == "deepseek-v4.1-flash-1017"


def test_minimax_gateway_availability_and_outage(monkeypatch):
    monkeypatch.setattr(type(settings), "get_api_key", lambda *_: "test-only")
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "direct")
    assert "minimax-m3.1-flash" not in {row["id"] for row in get_capabilities()["models"]}
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    model = next(row for row in get_capabilities()["models"] if row["provider"] == "minimax")
    assert model["configured"] and model["tier"] == "standard"
    monkeypatch.setattr(settings, "DISABLED_LLM_MODELS", "minimax-m3.1-flash")
    with pytest.raises(ValueError, match="暂停服务"):
        create_llm("minimax-m3.1-flash")


@pytest.mark.parametrize("purpose", ["speech", "reaction"])
def test_minimax_uses_low_reasoning_and_tool_structured_output(monkeypatch, purpose):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    model = create_game_model("minimax-m3.1-flash", purpose)
    assert isinstance(model, ReasoningChatOpenAI)
    payload = model._get_request_payload([HumanMessage(content="test")])
    assert payload["model"] == "minimax-m3.1-flash"
    assert payload["extra_body"] == {"reasoning_effort": "low"}
    structured = bind_reaction_output(model, "minimax-m3.1-flash")
    assert structured.first.kwargs["tools"][0]["function"]["name"] == "SpeechReactionPayload"
    assert "response_format" not in structured.first.kwargs
