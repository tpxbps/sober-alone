from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

from app.agents.agent_manager import AgentManager
from app.services.turn_errors import UNKNOWN_MESSAGE, mark_model_error, turn_error_message


def provider_error(status, body=None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.test/private"))
    error = APIStatusError("private prompt and secret", response=response, body=body)
    mark_model_error(error, "glm-5.3-flash")
    return error


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "model_request_rejected"),
        (422, "model_request_rejected"),
        (404, "model_unavailable"),
        (429, "model_rate_limited"),
        (503, "model_service_error"),
        (504, "model_timeout"),
        (401, "model_access_denied"),
        (403, "model_access_denied"),
    ],
)
def test_known_errors(status, code):
    actual, message = turn_error_message(provider_error(status))
    assert actual == code
    assert "glm-5.3-flash" in message and "大厅" in message
    assert "private" not in message and "secret" not in message and "宕机" not in message


@pytest.mark.parametrize(
    "code,expected",
    [
        ("context_length_exceeded", "model_context_limit"),
        ("content_policy_violation", "model_content_rejected"),
        ("model_not_found", "model_unavailable"),
    ],
)
def test_body_codes_precede_http_400(code, expected):
    assert (
        turn_error_message(provider_error(400, {"error": {"code": code, "message": "secret"}}))[0]
        == expected
    )


def test_wrapped_group_and_cycles():
    original = provider_error(400)
    wrapper = RuntimeError("internal details")
    wrapper.__cause__ = original
    original.__context__ = wrapper
    code, text = turn_error_message(ExceptionGroup("batch", [wrapper]))
    assert code == "model_request_rejected" and "glm-5.3-flash" in text and "internal" not in text


def test_unknown_is_not_guessed_from_text():
    assert turn_error_message(RuntimeError("HTTP 400 model down secret")) == (
        "execution_failed",
        UNKNOWN_MESSAGE,
    )
    assert turn_error_message(ValueError("invalid format"))[1] == UNKNOWN_MESSAGE


@pytest.mark.asyncio
async def test_reaction_attributes_listener_model_without_wrapping():
    error = provider_error(400)
    del error.game_model

    async def react(*args, **kwargs):
        raise error

    agent = SimpleNamespace(react_to_speech=react, reaction_llm_model="glm-5.3-flash")
    with pytest.raises(APIStatusError) as caught:
        await AgentManager._get_reaction_with_timeout(
            object.__new__(AgentManager), "listener", agent, "speaker", "text"
        )
    assert caught.value is error
    assert "glm-5.3-flash" in turn_error_message(error)[1]


@pytest.mark.asyncio
async def test_persisted_failure_keeps_draft_and_message(turns):
    from test_game_speech import until

    turns.error = provider_error(400)
    turns.text_gate.set()
    await turns.runner.start("game", "ai", "ai", request_id="provider-failed")
    turn, record = await until(turns.runner, "provider-failed", lambda t: t["status"] == "failed")
    assert turn["error_code"] == "model_request_rejected"
    assert "glm-5.3-flash" in turn["error_message"] and "大厅" in turn["error_message"]
    assert turn["content"] == "第一句。" and record is None and turns.calls == 1
    restored, _ = await turns.runner.snapshot("game", "provider-failed")
    assert restored["error_message"] == turn["error_message"]


@pytest.mark.parametrize(
    "error,code",
    [
        (httpx.ConnectError("secret"), "model_connection"),
        (httpx.ReadTimeout("secret"), "model_timeout"),
        (TimeoutError(), "model_timeout"),
    ],
)
def test_transport_failures(error, code):
    assert turn_error_message(error)[0] == code


def test_empty_and_untrusted_model_labels():
    error = provider_error(503)
    error.game_model = "secret-not-a-model"
    code, message = turn_error_message(error)
    assert code == "model_service_error" and "secret" not in message
    assert turn_error_message(RuntimeError(), empty_output=True)[0] == "model_empty_output"
