import pytest
from langgraph.types import Command

from app.game.content_quality import (
    CAPABILITY_VERSION,
    DIMENSIONS,
    RUBRIC_VERSION,
    content_fingerprint,
    public_ai_review,
    script_content,
)
from app.script_editor.nodes import quality_check


def content():
    return {
        "title": "测试",
        "difficulty": 1,
        "player_count": 1,
        "full_truth": "原有真相",
        "character_data": [
            {
                "character_id": "a",
                "name": "角色甲",
                "character_script": "昨夜我曾私下交谈。现在请公开解释你的行踪。",
            }
        ],
        "clue_stages": [{"stage": 1, "items": [{"id": "c01", "content": "公开物证"}]}],
    }


def test_content_fingerprint_matches_editor_db_and_excludes_assets():
    sections = content()
    normalized = script_content(sections)
    fingerprint = content_fingerprint(sections)
    assert fingerprint == content_fingerprint(normalized)
    normalized.update(cover_image_url="changed", ai_review={"score": 99})
    normalized["characters"][0]["voice_id"] = "changed"
    assert content_fingerprint(normalized) == fingerprint
    normalized["characters"][0]["character_script"] += "新的关键事实"
    assert content_fingerprint(normalized) != fingerprint


def test_ai_public_projection_hides_evidence_and_stale_scores():
    review = {
        "score": 60,
        "model": "gpt-6-astra",
        "content_fingerprint": "fp",
        "capability_version": CAPABILITY_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "dimensions": dict.fromkeys(DIMENSIONS, 3),
        "evidence": "凶手与秘密",
    }
    assert public_ai_review(review, "other") is None
    public = public_ai_review(review, "fp")
    assert public["score"] == 60
    assert "evidence" not in public
    assert sum(item["weight"] for item in public["dimensions"]) == 100
    assert next(item for item in public["dimensions"] if item["key"] == "narrative")["weight"] == 15
    review["rubric_version"] = "script-quality-v1"
    assert public_ai_review(review, "fp") is None
    review["rubric_version"] = RUBRIC_VERSION
    review["dimensions"]["fairness"] = 7
    assert public_ai_review(review, "fp") is None


class Judge:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, _schema, **_kwargs):
        return self

    async def ainvoke(self, _messages):
        if isinstance(self.result, Exception):
            raise self.result
        import json

        sources = json.loads(_messages[-1]["content"])["sources"]
        return {
            "findings": [
                {
                    **{k: finding[k] for k in ("severity", "impact", "suggestion")},
                    "source_id": next(
                        (
                            key
                            for key, value in sources.items()
                            if value["field"] == finding["field"]
                            and finding["evidence"] in value["text"]
                        ),
                        "invalid-source",
                    ),
                }
                for finding in self.result["findings"]
            ]
        }


def test_review_passages_preserve_every_character_and_nontext_value():
    text = "第一段。\n" * 200
    sources, values = quality_check.review_sources({"script": text, "rounds": [1, 2], "empty": []})
    assert "".join(item["text"] for item in sources.values()) == text
    assert all(item["field"] == "script" for item in sources.values())
    assert values == {"rounds[0]": 1, "rounds[1]": 2, "empty": []}


@pytest.mark.asyncio
async def test_historical_private_conversation_is_not_keyword_blocked(monkeypatch):
    monkeypatch.setattr(quality_check, "create_llm", lambda **kw: Judge({"findings": []}))
    state = {"game_data_sections": content()}
    state.update(await quality_check.check_game_quality(state))
    assert quality_check.quality_approved(state)
    assert state["quality_report"]["status"] == "passed"


@pytest.mark.asyncio
async def test_report_requires_source_evidence_and_approval_expires(monkeypatch):
    state = {"game_data_sections": content()}
    state["game_data_sections"]["character_data"][0]["character_script"] = "你现在必须私聊角色乙。"
    finding = {
        "severity": "major",
        "field": "characters[0].character_script",
        "evidence": "必须私聊",
        "impact": "当前无法执行",
        "suggestion": "改为公开讨论目标",
    }
    monkeypatch.setattr(quality_check, "create_llm", lambda **kw: Judge({"findings": [finding]}))
    state.update(await quality_check.check_game_quality(state))
    assert not quality_check.quality_approved(state)
    report = state["quality_report"]
    monkeypatch.setattr(
        quality_check,
        "interrupt",
        lambda payload: {"action": "accept_risk", "quality_report_id": report["report_id"]},
    )
    state.update(quality_check.review_quality(state))
    assert quality_check.quality_approved(state)
    state["game_data_sections"]["full_truth"] = "改动真相"
    assert not quality_check.quality_approved(state)
    with pytest.raises(ValueError, match="失效"):
        quality_check.review_quality(state)
    finding["evidence"] = "不在原文的内容"
    state.update(await quality_check.check_game_quality(state))
    assert state["quality_report"]["status"] == "incomplete"
    assert not quality_check.quality_approved(state)


@pytest.mark.asyncio
async def test_judge_failure_never_claims_passed_or_leaks_provider_details(monkeypatch):
    monkeypatch.setattr(
        quality_check, "create_llm", lambda **kw: Judge(TimeoutError("private-provider-detail"))
    )
    result = await quality_check.check_game_quality({"game_data_sections": content()})
    assert result["quality_report"]["status"] == "incomplete"
    assert "private-provider-detail" not in str(result)


@pytest.mark.asyncio
async def test_first_final_generation_waits_for_edited_review_and_human_input(monkeypatch):
    from app.script_editor import graph as graph_module
    from app.script_editor.nodes import final_draft

    monkeypatch.setattr(graph_module, "init_workflow", lambda s: {"current_step": "init"})
    monkeypatch.setattr(graph_module, "generate_outline", lambda s: {"outline": "大纲"})
    monkeypatch.setattr(graph_module, "generate_first_draft", lambda s: {"first_draft": "原始初稿"})
    monkeypatch.setattr(graph_module, "review_by_llm", lambda s: {"review_opinion": "原始AI意见"})
    calls = []

    async def llm(system, user):
        calls.append(user)
        return "完整终稿"

    monkeypatch.setattr(final_draft, "call_llm", llm)
    graph = graph_module.build_script_gen_graph()
    config = {"configurable": {"thread_id": "review-test"}}
    await graph.ainvoke({"workflow_mode": "create"}, config)
    await graph.ainvoke(Command(resume={"action": "confirm"}), config)
    await graph.ainvoke(Command(resume={"action": "confirm"}), config)
    assert graph.get_state(config).next == ("review_report",)
    assert not calls
    await graph.ainvoke(
        Command(
            resume={
                "action": "confirm",
                "content": "已修改AI意见",
                "human_review": "保留角色辩解线索",
            }
        ),
        config,
    )
    assert graph.get_state(config).next == ("review_final",)
    assert len(calls) == 1 and "已修改AI意见" in calls[0] and "保留角色辩解线索" in calls[0]
    assert "原始初稿" in calls[0]


def test_legacy_final_checkpoint_preserves_existing_human_review(monkeypatch):
    from app.script_editor.nodes import review_nodes

    monkeypatch.setattr(review_nodes, "interrupt", lambda payload: {"action": "confirm"})
    result = review_nodes.review_final({"final_draft": "终稿", "human_review": "旧意见"})
    assert result["human_review"] == "旧意见"
