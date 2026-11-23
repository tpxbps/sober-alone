import json

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.game_model_paths import bind_reaction_output, create_game_model, visible_speech_text
from app.api.schemas.script_editor import ChatRequest
from app.core.config import settings
from app.core.inference import GatewayAuth, InferenceRecoveryError, InferenceScope, inference_scope
from app.core.llm_factory import create_llm
from app.core.model_registry import MODEL_SPECS
from app.core.reasoning_chat import ReasoningChatOpenAI
from app.services import model_health
from app.services.capabilities import get_capabilities

FRONTIER = [spec for spec in MODEL_SPECS if spec.tier == "frontier" and spec.backends]


def test_kimi_k3_legacy_id_dispatches_to_k3_1_pro(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    models = {row["id"]: row for row in get_capabilities()["models"]}
    assert "kimi-k3" not in models
    assert models["kimi-k3.1-pro"]["name"] == "kimi-k3.1-pro"
    assert create_llm("kimi-k3").model_name == "kimi-k3.1-pro"


@pytest.mark.parametrize("backend", ["direct", "tokendance"])
@pytest.mark.parametrize("purpose", ["speech", "reaction"])
def test_qwen_thinking_is_scoped_to_role_speech(monkeypatch, backend, purpose):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", backend)
    monkeypatch.setattr(type(settings), "get_api_key", lambda *_: "test-only")
    monkeypatch.setattr(type(settings), "get_base_url", lambda *_: "https://provider.test/v1")
    model = create_game_model("qwen3.8-flash", purpose)
    assert isinstance(model, ReasoningChatOpenAI)
    assert model.extra_body == (
        {"enable_thinking": True, "reasoning_effort": "low"}
        if purpose == "speech"
        else {"enable_thinking": False}
    )
    # Switching role speech must not enable thinking in creator/summary requests.
    assert create_llm("qwen3.8-flash", disable_thinking=True).extra_body == {
        "enable_thinking": False
    }


@pytest.mark.parametrize(
    "spec", [s for s in MODEL_SPECS if s.id != "qwen3.8-flash" and "tokendance" in s.backends]
)
def test_other_game_models_keep_existing_inference_policy(monkeypatch, spec):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    old = create_llm(spec.id, disable_thinking=True)
    for purpose in ["speech", "reaction"]:
        current = create_game_model(spec.id, purpose)
        assert current.extra_body == old.extra_body
        assert current.model_name == old.model_name


def test_frontier_cannot_be_selected_for_creator_assistant():
    for spec in FRONTIER:
        assert (
            ChatRequest(message="hello", model=spec.id, chat_session_id="test").model
            == "deepseek-flash"
        )
    assert ChatRequest(message="hello", chat_session_id="test").model == "deepseek-flash"


def test_kimi_requests_low_reasoning_without_sampling_overrides(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    model = create_llm("kimi-k3.1-pro", disable_thinking=True)
    payload = model._get_request_payload([HumanMessage(content="test")])
    assert payload["extra_body"] == {"reasoning_effort": "low"}
    assert "temperature" not in payload
    assert model.max_tokens > 8192


@pytest.mark.parametrize(
    ("backend", "frontier_ids"),
    [("direct", set()), ("tokendance", {"kimi-k3.1-pro", "qwen4-max", "hy4"})],
)
def test_selectable_frontier_models_match_supported_routes(monkeypatch, backend, frontier_ids):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", backend)
    models = get_capabilities()["models"]
    assert {row["id"] for row in models if row["tier"] == "frontier"} == frontier_ids
    flash = [row["tier"] for row in models if row["id"] == "hy4-flash"]
    assert flash == (["standard"] if backend == "tokendance" else [])
    assert all(row["name"] == row["name"].lower() and " " not in row["name"] for row in models)


@pytest.mark.parametrize("model_id", ["hy4-flash", "hy4"])
def test_hunyuan_game_profiles_use_gateway_thinking_control_and_tool_output(monkeypatch, model_id):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    for purpose in ("speech", "reaction"):
        model = create_game_model(model_id, purpose)
        assert model.model_name == model_id
        assert model.extra_body == {"thinking": {"type": "disabled"}}
    bound = bind_reaction_output(model, model_id)
    assert bound.first.kwargs["tools"][0]["function"]["name"] == "SpeechReactionPayload"


def test_qwen4_max_game_profile(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    for purpose in ("speech", "reaction"):
        model = create_game_model("qwen4-max", purpose)
        assert model.model_name == "qwen4-max"
        assert model.extra_body == {"enable_thinking": False}
    assert next(spec for spec in FRONTIER if spec.id == "qwen4-max").reaction_output_method == (
        "function_calling"
    )


def test_gateway_catalog_retires_step_but_direct_mode_keeps_it(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    ids = {spec["id"] for spec in get_capabilities()["models"]}
    assert "step-3.5-flash" not in ids and "ling-3.0-flash" not in ids
    assert (
        create_llm("step-3.5-flash", disable_thinking=True).model_name == "deepseek-v4.1-flash-1017"
    )
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "direct")
    ids = {spec["id"] for spec in get_capabilities()["models"]}
    assert "step-3.5-flash" in ids and "ling-3.0-flash" not in ids
    assert "kimi-k3.1-pro" not in ids


@pytest.mark.asyncio
async def test_frontier_never_measured_even_on_forced_refresh(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    monkeypatch.setattr(type(settings), "get_api_key", lambda *_: "configured")
    seen = []

    async def measure(spec):
        seen.append(spec.id)
        return {"model": spec.id}

    model_health.clear_model_health_cache()
    try:
        for spec in FRONTIER:
            with pytest.raises(ValueError, match="Frontier"):
                await model_health._probe_model(spec)
        monkeypatch.setattr(model_health, "_probe_model", measure)
        await model_health.get_model_health(force_refresh=True)
        assert seen and not set(seen).intersection(spec.id for spec in FRONTIER)
    finally:
        model_health.clear_model_health_cache()


def test_reasoning_survives_stream_tools_and_next_turn_without_becoming_speech():
    model = ReasoningChatOpenAI(model="kimi-k3", api_key="test-only", max_retries=0)
    pieces = [
        {"reasoning_content": "private "},
        {"reasoning_content": "reasoning"},
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call1",
                    "type": "function",
                    "function": {"name": "recall", "arguments": "{}"},
                }
            ]
        },
    ]
    message = None
    for delta in pieces:
        chunk = model._convert_chunk_to_generation_chunk(
            {"choices": [{"delta": delta, "index": 0}]}, AIMessageChunk, None
        ).message
        assert visible_speech_text(chunk) == []
        message = chunk if message is None else message + chunk
    payload = model._get_request_payload(
        [
            HumanMessage(content="test"),
            message,
            ToolMessage(content="public clue", tool_call_id="call1"),
        ]
    )
    assert payload["messages"][1]["reasoning_content"] == "private reasoning"
    assert payload["messages"][1]["tool_calls"][0]["id"] == "call1"
    assert "private reasoning" not in str(payload["messages"][1]["content"])
    result = model._create_chat_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "answer",
                        "reasoning_content": "keep",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
    )
    saved = AIMessage(**result.generations[0].message.model_dump())
    assert model._get_request_payload([saved])["messages"][0]["reasoning_content"] == "keep"


def test_cached_client_rejects_frontier_under_trial_scope(monkeypatch):
    monkeypatch.setattr(settings, "TOKENDANCE_BASE_URL", "https://example.test/gateway")
    sent = []

    def dispatch(request):
        sent.append(json.loads(request.content)["model"])
        return httpx.Response(200)

    with httpx.Client(auth=GatewayAuth(), transport=httpx.MockTransport(dispatch)) as client:
        with inference_scope(
            InferenceScope("trial", lambda: "trial-key", allowed_models=frozenset({"cheap"}))
        ):
            client.post("https://example.test/gateway/v1/chat/completions", json={"model": "cheap"})
            with pytest.raises(InferenceRecoveryError):
                client.post(
                    "https://example.test/gateway/v1/chat/completions", json={"model": "kimi-k3"}
                )
        with inference_scope(InferenceScope("user", lambda: "user-key")):
            client.post(
                "https://example.test/gateway/v1/chat/completions", json={"model": "kimi-k3"}
            )
    assert sent == ["cheap", "kimi-k3"]
