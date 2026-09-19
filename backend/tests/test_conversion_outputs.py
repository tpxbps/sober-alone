import asyncio
from copy import deepcopy

import pytest

from app.script_editor.conversion import disclosure, service
from app.script_editor.conversion.cache import ConversionCache
from app.script_editor.conversion.public_material import PublicRole


@pytest.mark.asyncio
async def test_derived_failure_keeps_personal_script_after_restart(monkeypatch):
    calls = []
    fail = True

    async def invoke(_model, schema, _system, material, **kwargs):
        calls.append(schema.__name__)
        if schema is disclosure.PersonalScript:
            assert material["材料"] == [{"原文": "甲拿走账本。"}]
            return schema(character_script="我拿走了账本。")
        assert material["个人剧本"] == "我拿走了账本。"
        if fail:
            raise ValueError("派生暂时失败")
        return schema(script_summary="你拿走了账本。", system_prompt="你是甲，曾拿走账本。")

    async def public(*args):
        return PublicRole(
            character_id="role-a",
            profile="公开身份",
            appearance="灰衣",
            step_voice_id="wenrounansheng",
        )

    monkeypatch.setattr(service, "invoke", invoke)
    monkeypatch.setattr(service, "public_character", public)
    char = {"character_id": "role-a", "name": "甲"}
    state = {
        "disclosure_plan": {
            "characters": [char, {"name": "乙"}],
            "facts": [
                {
                    "quote": "甲拿走账本。",
                    "known_by": ["甲"],
                    "before_start": True,
                    "release": "reveal",
                },
                {
                    "quote": "乙后来到场。",
                    "known_by": ["乙"],
                    "before_start": True,
                    "release": "reveal",
                },
                {
                    "quote": "开局后鉴定发现毒物。",
                    "known_by": [],
                    "before_start": False,
                    "release": "round",
                },
            ],
        }
    }
    cache = ConversionCache("v1", {})
    state["_conversion_outputs"] = cache
    assert (await service._run_character(None, "story", char, state, ""))[1] is None
    fail = False
    state["_conversion_outputs"] = ConversionCache("v1", deepcopy(cache.results))
    result = (await service._run_character(None, "story", char, state, ""))[1]
    assert result.character_script == "我拿走了账本。"
    assert calls == ["PersonalScript", "RoleReading", "RoleReading"]


@pytest.mark.asyncio
async def test_shared_output_singleflight_and_dependency_invalidation():
    calls = 0

    async def generate():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return disclosure.PersonalScript(character_script="经历")

    cache = ConversionCache("v1", {})
    await asyncio.gather(
        *(cache.get("role", disclosure.PersonalScript, {"input": 1}, generate) for _ in range(4))
    )
    assert calls == 1
    await cache.get("role", disclosure.PersonalScript, {"input": 2}, generate)
    assert calls == 2


@pytest.mark.asyncio
async def test_repairs_only_invalid_facts_and_preserves_personal_action(monkeypatch):
    seen = []

    class Model:
        def model_copy(self, **kwargs):
            return self

    async def invoke(_model, schema, _system, material, **kwargs):
        seen.append(schema.__name__)
        if schema is disclosure.CastAndStart:
            value = schema(characters=[{"name": "甲"}], game_start="开局", start_source_id=1)
        elif schema is disclosure.FactBatch:
            value = schema(
                facts=[
                    {"source_id": 1, "known_by": ["甲"], "before_start": True, "release": "reveal"},
                    {"source_id": 2, "known_by": ["甲"], "before_start": True, "release": "reveal"},
                ]
            )
        else:
            assert [item["index"] for item in material["待修复事实"]] == [1]
            value = schema(
                repairs=[
                    {
                        "index": 1,
                        "facts": [
                            {
                                "source_id": 2,
                                "quote": "甲锁门",
                                "known_by": ["甲"],
                                "before_start": True,
                                "release": "reveal",
                            },
                            {
                                "source_id": 2,
                                "quote": "不知道乙来过",
                                "known_by": [],
                                "before_start": True,
                                "release": "reveal",
                            },
                        ],
                    }
                ]
            )
        if kwargs.get("validate"):
            kwargs["validate"](value)
        return value

    monkeypatch.setattr(disclosure, "invoke", invoke)
    state = {
        "final_draft": "甲拿走账本。甲锁门，不知道乙来过。",
        "player_count": 1,
        "num_clue_rounds": 1,
    }
    plan = await disclosure.extract_plan(Model(), state)
    assert seen == ["CastAndStart", "FactBatch", "FactRepairs"]
    assert disclosure.audience_material({"disclosure_plan": plan}, role="甲") == {
        "材料": [{"原文": "甲拿走账本。"}, {"原文": "甲锁门"}]
    }


def test_fact_batches_use_character_budget_without_24_sentence_fragmentation():
    source = "甲曾到过书房，带走了一份签过字的旧合同，但没有看见其他人。" * 90
    sources, batches = disclosure.source_batches(source)
    assert len(batches) == 1
    assert len(batches[0]) == 90
    assert "".join(sources.values()) == source


@pytest.mark.parametrize(
    "quote",
    ["委托人是谁，她不知道。", "她不知道那是不是自己的名字。", "她不知道这是试探还是信任。"],
)
def test_open_questions_are_not_misclassified_as_secret_inventory(quote):
    assert not disclosure.contains_unknown_evidence(quote)


def test_negated_arrival_still_reveals_the_secret():
    assert disclosure.contains_unknown_evidence("她不知道乙来过书房。")


@pytest.mark.asyncio
async def test_conflicting_scopes_on_one_quote_are_repaired_without_widening_knowledge(monkeypatch):
    class Model:
        def model_copy(self, **kwargs):
            return self

    async def invoke(_model, schema, _system, material, **kwargs):
        if schema is disclosure.CastAndStart:
            value = schema(
                characters=[{"name": "甲"}, {"name": "乙"}], game_start="次日", start_source_id=2
            )
        elif schema is disclosure.FactBatch:
            value = schema(
                facts=[
                    {"source_id": 1, "known_by": [name], "before_start": True, "release": "reveal"}
                    for name in ["甲", "乙"]
                ]
            )
        else:
            assert [item["index"] for item in material["待修复事实"]] == [0, 1]
            value = schema(
                repairs=[
                    {
                        "index": index,
                        "facts": [
                            {
                                "source_id": 1,
                                "quote": quote,
                                "known_by": [name],
                                "before_start": True,
                                "release": "reveal",
                            }
                        ],
                    }
                    for index, name, quote in [(0, "甲", "甲锁门"), (1, "乙", "乙换杯")]
                ]
            )
        if kwargs.get("validate"):
            kwargs["validate"](value)
        return value

    monkeypatch.setattr(disclosure, "invoke", invoke)
    plan = await disclosure.extract_plan(
        Model(),
        {"final_draft": "甲锁门，乙换杯。开局于次日。", "player_count": 2, "num_clue_rounds": 1},
    )
    assert disclosure.audience_material({"disclosure_plan": plan}, role="甲") == {
        "材料": [{"原文": "甲锁门"}]
    }
    assert disclosure.audience_material({"disclosure_plan": plan}, role="乙") == {
        "材料": [{"原文": "乙换杯"}]
    }
