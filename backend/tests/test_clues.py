import pytest

from app.game.clues import (
    legacy_clue_stages,
    normalize_clue_stages,
    parse_clue_citations,
    public_clues,
    render_clue_markdown,
    render_clue_tts,
)


def legacy_script():
    return {
        "script_id": "legacy-1",
        "game_full_process": [
            {"type": "initial", "system_notice": "开场"},
            {
                "type": "advancement",
                "children": [
                    {"system_notice": "门锁没有撬动痕迹。窗台留有红泥。"},
                    {"system_notice": "请讨论线索。"},
                ],
            },
        ],
    }


def test_legacy_adapter_is_deterministic_and_preserves_text():
    first = legacy_clue_stages(legacy_script())
    second = legacy_clue_stages(legacy_script())

    assert first == second
    assert first[0]["items"][0]["id"] == "c01"
    assert first[0]["items"][0]["content"] == "门锁没有撬动痕迹。窗台留有红泥。"


def test_renderers_separate_markdown_from_tts_and_public_stage_scope():
    stages = normalize_clue_stages(None, **legacy_script())
    markdown = render_clue_markdown(stages[0])
    speech = render_clue_tts(stages[0])

    assert "## 第 1 轮公开线索" in markdown
    assert "###" in markdown
    assert "#" not in speech
    assert public_clues(stages, 0) == []
    assert public_clues(stages, 1) == stages[0]["items"]


def test_citation_parser_only_activates_revealed_ids():
    clue = legacy_clue_stages(legacy_script())[0]["items"][0]
    future_id = "c99"
    visible, refs, unknown = parse_clue_citations(
        f"据此判断 [{clue['id']}]，未来 [{future_id}]。", [clue], strip_unknown=True
    )

    assert refs == [clue["id"]]
    assert unknown == [future_id]
    assert f"[{clue['id']}]" in visible
    assert f"[{future_id}]" in visible


def test_citation_parser_repairs_code_links_and_bare_ids_in_place():
    clues = [
        {"id": "c02", "summary": "广播", "content": "广播持续九秒", "stage": 1},
        {"id": "c04", "summary": "设备", "content": "服务器停用", "stage": 1},
        {"id": "c06", "summary": "清单", "content": "母带销毁", "stage": 1},
    ]
    content = (
        "c02 明确记录广播持续九秒。`[c02]`\n"
        "[设备记录](#clue-ref-c04) 显示服务器停用。\n"
        "至于清单 c06，我仍需解释。"
    )

    normalized, refs, unknown = parse_clue_citations(content, clues, strip_unknown=True)

    assert normalized == (
        "明确记录广播持续九秒。[c02]\n[c04] 显示服务器停用。\n至于清单 [c06]，我仍需解释。"
    )
    assert refs == ["c02", "c04", "c06"]
    assert unknown == []


def test_missing_ids_are_compact_and_do_not_renumber_existing_items():
    stages = normalize_clue_stages(
        [
            {
                "stage": 1,
                "items": [
                    {"id": "c02", "summary": "既有", "content": "既有内容"},
                    {"id": "", "summary": "新增", "content": "新增内容"},
                ],
            }
        ],
        script_id="script",
    )

    assert [item["id"] for item in stages[0]["items"]] == ["c02", "c01"]


def test_normalization_rejects_empty_round():
    with pytest.raises(ValueError, match="至少需要一条线索"):
        normalize_clue_stages([{"stage": 1, "overview": "", "items": []}], script_id="script")
