import json

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

from app.agents.game_model_paths import visible_speech_text
from app.api.schemas.script_editor import ChatRequest
from app.core.config import settings
from app.core.inference import GatewayAuth, InferenceRecoveryError, InferenceScope, inference_scope
from app.core.llm_factory import create_llm
from app.core.model_registry import MODEL_SPECS
from app.core.reasoning_chat import ReasoningChatOpenAI
from app.services import model_health
from app.services.capabilities import get_capabilities

FRONTIER = [spec for spec in MODEL_SPECS if spec.tier == "frontier"]


def test_frontier_cannot_be_selected_for_creator_assistant():
    for spec in FRONTIER:
        with pytest.raises(ValueError, match="前沿模型仅供游戏"):
            ChatRequest(message="hello", model=spec.id, chat_session_id="test")
    assert ChatRequest(message="hello", chat_session_id="test").model == "deepseek-flash"


@pytest.mark.parametrize("spec", FRONTIER, ids=lambda spec: spec.id)
def test_frontier_parameters_never_default_to_max(monkeypatch, spec):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    model = create_llm(spec.id, disable_thinking=True)
    payload = model._get_request_payload([HumanMessage(content="test")])
    assert payload["extra_body"]["reasoning_effort"] == "low"
    if spec.provider == "moonshot":
        assert "temperature" not in payload
        assert "thinking" not in payload["extra_body"]
        assert model.max_tokens > 8192


def test_gateway_catalog_retires_step_but_direct_mode_keeps_it(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    ids = {spec["id"] for spec in get_capabilities()["models"]}
    assert "step-3.5-flash" not in ids and "ling-3.0-flash" in ids
    assert create_llm("step-3.5-flash", disable_thinking=True).model_name == "ling-3.0-flash"
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "direct")
    ids = {spec["id"] for spec in get_capabilities()["models"]}
    assert "step-3.5-flash" in ids and "ling-3.0-flash" not in ids
    assert not ids.intersection(spec.id for spec in FRONTIER)


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
