import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import BadRequestError

from app.script_editor.asset_generation import service as assets
from app.script_editor.nodes import safety_check as safety
from app.script_editor.services import image_gen
from app.script_editor.services.progress_registry import asset_progress_registry as registry


def test_safety_batches_deduplicate_without_dropping_locations_or_tail():
    sections = {f"short_{i}": f"短字段{i}" for i in range(85)}
    sections.update(personal_script="正文" * 4000 + "尾部", legacy_script="正文" * 4000 + "尾部")
    batches = list(safety.review_batches(sections))
    items = [item for batch in batches for item in batch]
    assert len(batches) < 10
    assert len({item["text"] for item in items}) == len(items)
    assert any(item["text"].endswith("尾部") for item in items)
    original = list(safety.review_chunks(sections))
    assert sum(len(item["locations"]) for item in items) == len(original)
    for chunk in original:
        assert any(
            item["text"] == chunk["text"]
            and {"field": chunk["field"], "start": chunk["start"]} in item["locations"]
            for item in items
        )


@pytest.mark.asyncio
async def test_batched_safety_keeps_per_item_results_and_reuses_cache(monkeypatch):
    calls = []

    class Judge:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            items = json.loads(messages[-1]["content"])["items"]
            calls.append(items)
            return {
                "results": [
                    {
                        "id": item["id"],
                        "status": "FAIL" if item["text"] == "需拒绝" else "PASS",
                        "reason": "具体原因" if item["text"] == "需拒绝" else "",
                    }
                    for item in items
                ]
            }

    monkeypatch.setattr("app.script_editor.llm.create_llm", lambda **kwargs: Judge())
    state = {"game_data_sections": {"a": "正常", "b": "正常", "c": "需拒绝"}}
    state.update(await safety.safety_check(state))
    assert len(calls) == 1 and len(calls[0]) == 2
    assert state["safety_report"]["passed"] == 1
    assert state["safety_rejection_reason"] == "c：具体原因"
    await safety.safety_check(state)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_missing_batch_results_fail_closed(monkeypatch):
    class Judge:
        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, messages):
            return {"results": []}

    monkeypatch.setattr("app.script_editor.llm.create_llm", lambda **kwargs: Judge())
    result = await safety.safety_check({"game_data_sections": {"description": "必须覆盖"}})
    assert not result["safety_passed"]
    assert result["safety_report"]["status"] == "error"


@pytest.mark.asyncio
async def test_three_retries_survive_reload_and_then_complete_with_fallback(monkeypatch):
    sid = "retry-budget"
    generate = AsyncMock(return_value=None)
    monkeypatch.setattr(image_gen, "generate_cover_image", generate)
    state = {
        "asset_progress": {
            "phases": [
                {
                    "id": "image",
                    "tasks": [
                        {"id": "cover", "status": "failed"},
                        {"id": "avatar_a", "status": "complete"},
                    ],
                }
            ]
        }
    }
    for count in range(1, 4):
        registry.reset(sid)
        await assets.AssetGenerationService().retry(sid, "cover", state)
        state["asset_progress"] = registry.snapshot(sid)
        task = state["asset_progress"]["phases"][0]["tasks"][0]
        assert task["retry_count"] == count
        assert task["status"] == ("failed" if count < 3 else "skipped")
    assert state["asset_progress"]["isComplete"]
    assert task["fallback"] and task["retry_exhausted"]
    registry.reset(sid)
    await assets.AssetGenerationService().retry(sid, "cover", state)
    assert generate.await_count == 3
    registry.reset(sid)


@pytest.mark.asyncio
async def test_replayed_retry_operation_does_not_spend_another_attempt(monkeypatch):
    from app.script_editor.outline.runtime import current_runtime

    sid = "replay-budget"
    generate = AsyncMock(return_value=None)
    monkeypatch.setattr(image_gen, "generate_cover_image", generate)
    state = {"asset_progress": {"phases": [{"tasks": [{"id": "cover", "status": "failed"}]}]}}
    runtime = SimpleNamespace(operation_id="op-1", drain_progress=AsyncMock())
    token = current_runtime.set(runtime)
    try:
        await assets.AssetGenerationService().retry(sid, "cover", state)
        await assets.AssetGenerationService().retry(sid, "cover", state)
        assert generate.await_count == 1
        assert registry.snapshot(sid)["phases"][0]["tasks"][0]["retry_count"] == 1
    finally:
        current_runtime.reset(token)
        registry.reset(sid)


@pytest.mark.asyncio
async def test_provider_rejection_is_not_reported_as_empty_image(tmp_path, monkeypatch):
    response = httpx.Response(400, request=httpx.Request("POST", "https://image.example/generate"))
    generate = AsyncMock(
        side_effect=BadRequestError(
            "rejected",
            response=response,
            body={"error": {"code": "InputTextSensitiveContentDetected"}},
        )
    )
    monkeypatch.setattr(
        image_gen,
        "_get_doubao_client",
        lambda: SimpleNamespace(images=SimpleNamespace(generate=generate)),
    )
    monkeypatch.setattr(image_gen.settings, "DOUBAO_API_KEY", "test-key")
    with pytest.raises(image_gen.ImageGenerationRejected, match="默认展示"):
        await image_gen._generate_image("封面场景", tmp_path / "cover.png")
    assert generate.await_count == 1
    assert not (tmp_path / "cover.png").exists()


@pytest.mark.asyncio
async def test_rejected_image_is_terminal_and_other_assets_keep_running(monkeypatch):
    sid = "permanent-rejection"
    registry.init(
        sid,
        [
            {
                "tasks": [
                    {"id": "cover", "status": "pending"},
                    {"id": "avatar_a", "status": "running"},
                ]
            }
        ],
    )
    generate = AsyncMock(side_effect=image_gen.ImageGenerationRejected("图片服务未接受本次内容"))
    monkeypatch.setattr(image_gen, "generate_cover_image", generate)
    await assets._run_single_image(sid, "cover", "generate_cover_image", {})
    progress = registry.snapshot(sid)
    assert progress["phases"][0]["tasks"][0]["status"] == "skipped"
    assert not progress["isComplete"]
    await assets.AssetGenerationService().retry(sid, "cover", {})
    assert generate.await_count == 1
    registry.reset(sid)
