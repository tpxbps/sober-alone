"""Failure-driven regressions for bounded generation and author intent."""

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_outline_cocreation import QUESTION

from app.script_editor.conversion import disclosure
from app.script_editor.llm import StructuredOutputTruncated, invoke_structured
from app.script_editor.outline import nodes
from app.script_editor.outline.contracts import Direction, new_session
from app.script_editor.outline.revisions import OutlineRevision, apply_outline_input


class Model:
    def __init__(self, results=()):
        self.results = iter(results)
        self.messages = []

    def model_copy(self, update):
        assert update["max_tokens"] == 8192
        return self

    def with_structured_output(self, schema, **kwargs):
        assert kwargs["method"] == "function_calling"
        return self

    async def ainvoke(self, messages):
        self.messages.append(deepcopy(messages))
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result


def test_ask_contract_accepts_no_future_writing_task_or_recommendation():
    question = {k: v for k, v in QUESTION.items() if k != "recommended_option_id"}
    result = Direction(action="ask", question=question)
    assert result.next_task == "" and result.question.recommended_option_id is None
    with pytest.raises(ValueError, match="下一段"):
        Direction(action="continue")


@pytest.mark.asyncio
async def test_structural_repair_receives_exact_field_and_only_retries_once():
    model = Model(
        [{"action": "ask", "question": {"title": "问题"}}, {"action": "ask", "question": QUESTION}]
    )
    result = await invoke_structured(model, Direction, "共创", "开篇")
    assert result.action == "ask"
    assert len(model.messages) == 2
    assert "question.options" in model.messages[1][-1]["content"]


@pytest.mark.asyncio
async def test_truncation_never_repeats_the_same_oversized_request():
    raw = SimpleNamespace(
        response_metadata={"finish_reason": "length"},
        tool_calls=[],
        invalid_tool_calls=[],
        usage_metadata=None,
    )
    model = Model([{"raw": raw, "parsed": None}])
    with pytest.raises(StructuredOutputTruncated):
        await invoke_structured(model, Direction, "共创", "开篇")
    assert len(model.messages) == 1


@pytest.mark.asyncio
async def test_correcting_the_past_does_not_answer_the_current_question(monkeypatch):
    question = {**QUESTION, "id": "current-question"}
    session = new_session()
    session["pending_input"] = {
        "question": question,
        "other_text": "他们自愿合作",
        "after": "write",
    }

    async def repair(*args, **kwargs):
        return OutlineRevision(
            edits=[{"id": "p1", "content": "他们自愿合作。"}],
            canon=["自愿合作"],
            summary="已调整人物关系。",
            question_answered=False,
        )

    monkeypatch.setattr(nodes, "structured", repair)
    result = await apply_outline_input({"outline": "甲逼迫乙。", "outline_session": session})
    assert result["outline"] == "他们自愿合作。"
    assert result["outline_session"]["pending_question"] == question
    assert result["outline_session"]["next_action"] == "wait"
    assert not result["outline_session"]["decisions"]


def fact(source_id):
    return {
        "source_id": source_id,
        "known_by": ["甲"],
        "actors": ["甲"],
        "before_start": True,
        "release": "reveal",
    }


@pytest.mark.asyncio
async def test_failed_fact_batch_reuses_completed_siblings_and_cast(monkeypatch):
    calls = []
    fail = True

    async def invoke(_model, schema, _system, material, **kwargs):
        nonlocal fail
        if schema is disclosure.CastAndStart:
            calls.append("cast")
            value = schema(characters=[{"name": "甲"}], game_start="开局", start_source_id=1)
        else:
            ids = list(material["本批片段"])
            calls.append(ids[0])
            if ids[0] == 1 and fail:
                fail = False
                raise ValueError("本批校验失败")
            value = schema(facts=[fact(i) for i in ids])
        kwargs["validate"](value)
        return value

    monkeypatch.setattr(disclosure, "invoke", invoke)
    state = {"final_draft": "甲看到了灯灭。" * 40, "player_count": 1, "num_clue_rounds": 1}
    with pytest.raises(ValueError, match="本批"):
        await disclosure.extract_plan(Model(), state)
    assert list(state["disclosure_cache"]["batches"]) == ["25-40"]
    result = await disclosure.extract_plan(Model(), state)
    assert len(result["facts"]) == 40
    assert calls == ["cast", 1, 25, 1]


@pytest.mark.asyncio
async def test_fact_truncation_splits_instead_of_dropping_material(monkeypatch):
    sizes = []

    async def invoke(_model, schema, _system, material, **kwargs):
        if schema is disclosure.CastAndStart:
            value = schema(characters=[{"name": "甲"}], game_start="开局", start_source_id=1)
        else:
            ids = list(material["本批片段"])
            sizes.append(len(ids))
            if len(ids) > 2:
                raise StructuredOutputTruncated()
            value = schema(facts=[fact(i) for i in ids])
        kwargs["validate"](value)
        return value

    monkeypatch.setattr(disclosure, "invoke", invoke)
    state = {"final_draft": "甲看到了灯灭。" * 4, "player_count": 1, "num_clue_rounds": 1}
    result = await disclosure.extract_plan(Model(), state)
    assert sizes == [4, 2, 2]
    assert {f["source_id"] for f in result["facts"]} == {1, 2, 3, 4}
    assert "全稿" not in json.dumps(
        disclosure.audience_material({"disclosure_plan": result}, role="甲")
    )


def test_excerpt_restores_formatting_without_accepting_changed_facts():
    source = "- **老友甲折返书房**：与老板发生争执。"
    excerpt = disclosure.source_excerpt("老友甲折返书房：与老板发生争执。", source)
    assert excerpt and excerpt in source
    assert disclosure.source_excerpt("老友乙折返书房：与老板发生争执。", source) is None


@pytest.mark.parametrize("wording", ["不知道", "本不得提前知道", "不应知晓", "不能事先得知"])
def test_author_only_knowledge_restrictions_never_enter_personal_material(wording):
    quote = f"甲{wording}乙到过书房。"
    plan = {
        "characters": [{"name": "甲"}, {"name": "乙"}],
        "facts": [
            {"quote": quote, "known_by": ["甲"], "before_start": True, "release": "reveal"},
            {
                "quote": "甲拿走了账本。",
                "known_by": ["甲"],
                "before_start": True,
                "release": "reveal",
            },
        ],
    }
    personal = disclosure.audience_material({"disclosure_plan": plan}, role="甲")
    assert personal["材料"] == [{"原文": "甲拿走了账本。"}]
    assert quote in json.dumps(
        disclosure.audience_material({"disclosure_plan": plan}, scope="truth"), ensure_ascii=False
    )


def test_partial_role_knowledge_cannot_become_public_even_in_legacy_plan():
    plan = {
        "characters": [{"name": "甲"}, {"name": "乙"}],
        "facts": [
            {
                "quote": "甲调换了杯子。",
                "known_by": ["甲"],
                "before_start": True,
                "release": "public",
            },
        ],
    }
    assert not disclosure.audience_material({"disclosure_plan": plan}, role="乙")["材料"]
    assert disclosure.audience_material({"disclosure_plan": plan}, role="甲")["材料"]


def test_personal_output_cannot_inventory_unknown_secret_actions():
    with pytest.raises(ValueError, match="否定句"):
        disclosure.validate_no_secret_inventory(
            "我不知道乙到过书房，也不知道丙开过窗。", "甲", ["甲", "乙", "丙"]
        )
    disclosure.validate_no_secret_inventory(
        "我拿走了账本，但不知道是谁杀了他。", "甲", ["甲", "乙", "丙"]
    )


@pytest.mark.asyncio
async def test_whole_json_fallback_keeps_schema_validation():
    raw = SimpleNamespace(
        response_metadata={"finish_reason": "stop"},
        tool_calls=[],
        invalid_tool_calls=[],
        content='{"action":"continue","next_task":"动机"}',
    )
    result = await invoke_structured(
        Model([{"raw": raw, "parsed": None}]), Direction, "共创", "大纲"
    )
    assert result.next_task == "动机"
    raw.content = '这不是完整的 JSON {"action":"continue"}'
    with pytest.raises(ValueError):
        await invoke_structured(
            Model([{"raw": raw, "parsed": None}] * 2), Direction, "共创", "大纲"
        )


@pytest.mark.asyncio
async def test_nested_calls_share_a_concurrency_limit():
    active, peak = 0, 0

    class ConcurrentModel(Model):
        async def ainvoke(self, _messages):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return Direction(action="continue", next_task="继续")

    await asyncio.gather(
        *(invoke_structured(ConcurrentModel(), Direction, "共创", "大纲") for _ in range(12))
    )
    assert peak == 4


@pytest.mark.asyncio
async def test_missing_role_material_invalidates_only_related_cached_batches(monkeypatch):
    async def invoke(_model, schema, _system, material, **kwargs):
        value = (
            schema(characters=[{"name": "甲"}], game_start="开局", start_source_id=1)
            if schema is disclosure.CastAndStart
            else schema(facts=[])
        )
        kwargs["validate"](value)
        return value

    monkeypatch.setattr(disclosure, "invoke", invoke)
    state = {"final_draft": "甲看到了灯灭。", "player_count": 1, "num_clue_rounds": 1}
    with pytest.raises(ValueError, match="遗漏 甲"):
        await disclosure.extract_plan(Model(), state)
    assert state["disclosure_cache"]["batches"] == {}
    assert "甲" in state["disclosure_cache"]["coverage_feedback"]


def test_fact_uses_one_knowledge_classification_with_legacy_actor_compatibility():
    value = disclosure.Fact.model_validate(
        {
            "quote": "甲找到乙说了一句话。",
            "known_by": ["乙"],
            "actors": ["甲"],
            "before_start": True,
            "release": "reveal",
        }
    )
    assert value.known_by == ["乙"]
    assert "actors" not in disclosure.Fact.model_json_schema()["properties"]
    assert "actors" not in value.model_dump()


def test_unresolved_question_is_not_a_negative_inventory_of_secret_facts():
    assert not disclosure.contains_unknown_evidence(
        "甲怀疑两位老客人，但不知道谁才是真正该负责的人。"
    )
    assert not disclosure.contains_unknown_evidence("甲不知道是谁杀了他。")
    assert disclosure.contains_unknown_evidence("甲不知道乙来过书房。")


def test_empty_knowledge_is_not_implicitly_public():
    plan = {
        "characters": [{"name": "甲"}, {"name": "乙"}],
        "facts": [
            {"quote": "门锁上有线头。", "known_by": [], "before_start": True, "release": "public"},
        ],
    }
    assert not disclosure.audience_material({"disclosure_plan": plan}, role="甲")["材料"]


@pytest.mark.asyncio
@pytest.mark.parametrize("round_number", [None, 0, 3])
async def test_generated_round_labels_fit_the_authors_selected_round_count(
    monkeypatch, round_number
):
    async def invoke(_model, schema, _system, material, **kwargs):
        if schema is disclosure.CastAndStart:
            value = schema(characters=[{"name": "甲"}], game_start="开局", start_source_id=1)
        else:
            value = schema(facts=[{**fact(1), "release": "round", "round": round_number}])
        kwargs["validate"](value)
        return value

    monkeypatch.setattr(disclosure, "invoke", invoke)
    result = await disclosure.extract_plan(
        Model(), {"final_draft": "甲拿走账本。", "player_count": 1, "num_clue_rounds": 1}
    )
    assert result["facts"][0]["round"] == 1
    assert result["facts"][0]["known_by"] == ["甲"]


@pytest.mark.parametrize("backend", ["inherit", "deepseek_official"])
def test_explicit_official_route_still_respects_operator_model_disable(monkeypatch, backend):
    from app.script_editor import llm

    monkeypatch.setattr(llm.settings, "SCRIPT_EDITOR_INFERENCE_BACKEND", backend)
    monkeypatch.setattr(llm.settings, "DISABLED_LLM_MODELS", "deepseek-flash")
    with pytest.raises(ValueError, match="暂时不可用"):
        llm.create_editor_llm()
