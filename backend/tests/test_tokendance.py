import asyncio
import json

import httpx
import pytest

from app.core.config import settings
from app.core.inference import (
    GatewayAuth,
    InferenceRecoveryError,
    InferenceScope,
    check_gateway_response,
    gateway_async_client,
    gateway_model,
    inference_scope,
)
from app.rag.embeddings import DIMENSIONS, embed
from app.services.minimax_tts import MiniMaxTTSSession


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_BACKEND", "tokendance")
    monkeypatch.setattr(settings, "TOKENDANCE_REQUIRE_SCOPE", True)
    monkeypatch.setattr(settings, "TOKENDANCE_APP_URL", "https://example.test/")


@pytest.mark.asyncio
async def test_cached_client_uses_current_principal_and_revocation(gateway):
    keys = {"a": "test-key-a", "b": "test-key-b"}

    async def handler(request):
        await asyncio.sleep(0)
        assert request.headers["X-App-URL"] == "https://example.test/"
        return httpx.Response(200, json={"authorization": request.headers["Authorization"]})

    async with gateway_async_client(transport=httpx.MockTransport(handler)) as client:

        async def call(principal):
            with inference_scope(InferenceScope(principal, lambda: keys.get(principal, ""))):
                return (await client.get("https://tokendance.space/gateway/v1/models")).json()

        a, b = await asyncio.gather(call("a"), call("b"))
        assert a["authorization"] == "Bearer test-key-a"
        assert b["authorization"] == "Bearer test-key-b"
        keys.pop("a")
        with pytest.raises(InferenceRecoveryError):
            await call("a")


def test_key_cannot_leave_configured_origin(gateway):
    with inference_scope(InferenceScope("test", lambda: "test-key")):
        with httpx.Client(
            auth=GatewayAuth(), transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ) as client:
            with pytest.raises(ValueError):
                client.get("https://other.test/")
            with pytest.raises(ValueError):
                client.get("https://tokendance.space:8443/")


@pytest.mark.parametrize("action", ["top_up_balance", "reauthorize_api_key", "api_key_quota"])
def test_recovery_contract(action):
    with pytest.raises(InferenceRecoveryError) as caught:
        check_gateway_response(httpx.Response(402, headers={"TokenDance-Recovery-Action": action}))
    assert caught.value.action == action


def test_model_aliases():
    assert gateway_model("deepseek-flash") == "deepseek-v4.1-flash"
    assert gateway_model("doubao-seed-2-0-mini-260215") == "seed-2.0-mini"


def test_legacy_voice_gender_survives_without_character_metadata():
    from app.script_editor.conversion.service import STEP_FEMALE_VOICES, STEP_MALE_VOICES
    from app.services.voices import MINIMAX_VOICES, resolve_minimax_voice

    genders = {voice: gender for voice, _, gender in MINIMAX_VOICES}
    for voices, expected in ((STEP_FEMALE_VOICES, "女"), (STEP_MALE_VOICES, "男")):
        assert all(genders[resolve_minimax_voice(voice)] == expected for voice in voices)


def test_embeddings_sort_and_reject_incomplete_batches(monkeypatch, gateway):
    from app.rag import embeddings

    rows = [
        {"index": 1, "embedding": [0.2] * DIMENSIONS},
        {"index": 0, "embedding": [0.1] * DIMENSIONS},
    ]
    monkeypatch.setattr(
        embeddings,
        "gateway_client",
        lambda **_: httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"data": rows}))
        ),
    )
    assert embed(["first", "second"])[0][0] == 0.1
    rows.pop()
    with pytest.raises(ValueError):
        embed(["first", "second"])


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_minimax_final_frame_does_not_repeat_incremental_audio(
    monkeypatch, gateway, complete
):
    from app.services import minimax_tts

    frames = [{"data": {"status": 1, "audio": b"first".hex()}}]
    if complete:
        frames += [
            {
                "data": {"status": 2, "audio": b"first-last".hex()},
                "extra_info": {"usage_characters": 3},
            }
        ]
    wire = "".join("data: " + json.dumps(item) + "\n\n" for item in frames)
    monkeypatch.setattr(
        minimax_tts,
        "gateway_async_client",
        lambda **_: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text=wire))
        ),
    )
    with inference_scope(InferenceScope("test", lambda: "test-key")):
        session = MiniMaxTTSSession()
        await session.connect("male-qn-qingse")
        await session.send_text("测试")
        if not complete:
            with pytest.raises(RuntimeError):
                _ = [chunk async for chunk in session.receive_audio()]
        else:
            import base64

            audio = b"".join(
                [base64.b64decode(chunk["audio"]) async for chunk in session.receive_audio()]
            )
            assert audio == b"first-last"
            assert session.usage_characters == 3


@pytest.mark.asyncio
async def test_sdk_wrapped_recovery_is_not_a_normal_network_error(gateway):
    from openai import APIConnectionError, AsyncOpenAI

    from app.core.inference import raise_for_inference_recovery

    transport = httpx.MockTransport(
        lambda _: httpx.Response(402, headers={"TokenDance-Recovery-Action": "top_up_balance"})
    )
    async with gateway_async_client(transport=transport) as http:
        sdk = AsyncOpenAI(
            api_key="placeholder",
            base_url="https://tokendance.space/gateway/v1",
            http_client=http,
            max_retries=0,
        )
        with inference_scope(InferenceScope("test", lambda: "test-key")):
            with pytest.raises(APIConnectionError) as wrapped:
                await sdk.chat.completions.create(
                    model="step-3.5-flash", messages=[{"role": "user", "content": "test"}]
                )
            with pytest.raises(InferenceRecoveryError) as caught:
                raise_for_inference_recovery(wrapped.value)
            assert caught.value.action == "top_up_balance"


@pytest.mark.asyncio
async def test_minimax_excludes_aggregate_and_handles_empty_terminal(monkeypatch, gateway):
    from app.services import minimax_tts

    def handle(request):
        assert json.loads(request.content)["stream_options"]["exclude_aggregated_audio"] is True
        return httpx.Response(
            200,
            text='data: {"data":{"status":1,"audio":"616263"}}\n\ndata: {"data":{"status":2,"audio":""}}\n\n',
        )

    monkeypatch.setattr(
        minimax_tts,
        "gateway_async_client",
        lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    with inference_scope(InferenceScope("test", lambda: "test-key")):
        session = MiniMaxTTSSession()
        await session.connect("male-qn-jingying")
        await session.send_text("测试")
        assert [chunk["audio"] async for chunk in session.receive_audio()] == ["YWJj"]
        await session.close()
        assert not session.is_connected


def test_voice_migration_validates_all_roles_and_preserves_rollback(tmp_path, gateway):
    import copy
    import sqlite3

    from app.services.tokendance_migration import apply_voices, manifest_for, source_rows

    path = tmp_path / "game.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE characters (character_id TEXT PRIMARY KEY, script_id TEXT, name TEXT, gender TEXT, age INT, occupation TEXT, profile TEXT, character_script TEXT, voice_id TEXT, voice_provider TEXT)"
        )
        db.execute(
            "INSERT INTO characters VALUES ('one','script','测试角色','男',65,'医生','沉稳','角色私有信息','cixingnansheng','stepfun')"
        )
    manifest = manifest_for(source_rows(path))
    damaged = copy.deepcopy(manifest)
    damaged["characters"] = []
    with pytest.raises(ValueError, match="every source character"):
        apply_voices(path, damaged)
    assert not path.with_name("game.db.before-tokendance").exists()
    apply_voices(path, manifest)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT voice_id, voice_provider FROM characters").fetchone() == (
            "Chinese (Mandarin)_Humorous_Elder",
            "minimax",
        )
    with sqlite3.connect(path.with_name("game.db.before-tokendance")) as db:
        assert db.execute("SELECT voice_id FROM characters").fetchone()[0] == "cixingnansheng"
    with pytest.raises(ValueError, match="Source changed"):
        apply_voices(path, manifest)


@pytest.mark.asyncio
async def test_gateway_deepseek_uses_supported_function_calling(gateway):
    from pydantic import BaseModel

    from app.agents.game_model_paths import bind_reaction_output
    from app.core.llm_factory import create_llm

    class Result(BaseModel):
        answer: str

    model = create_llm("deepseek-flash", disable_thinking=True)
    structured = bind_reaction_output(model, "deepseek-flash", Result)
    binding = structured.steps[0]
    assert "tools" in binding.kwargs
    assert "response_format" not in binding.kwargs
