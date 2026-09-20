import json
from pathlib import Path

import pytest

from app.game.citation_stream import CitationStreamFilter
from app.game.citation_syntax import speech_text
from app.game.clues import parse_clue_citations

FIXTURE = json.loads(
    (Path(__file__).parents[2] / "fixtures/clue-citations.json").read_text(encoding="utf-8")
)
CLUES = [
    {"id": id, "summary": FIXTURE["names"][id], "content": "正文", "stage": 1}
    for id in FIXTURE["allowed"]
]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_shared_protocol(case):
    ai, refs, unknown = parse_clue_citations(case["input"], CLUES, strip_unknown=True)
    assert (ai, refs, unknown) == (case["ai"], case["refs"], case["unknown"])
    assert parse_clue_citations(ai, CLUES, strip_unknown=True)[0] == ai
    human, refs, unknown = parse_clue_citations(case["input"], CLUES, strip_unknown=False)
    assert refs == case["humanRefs"]
    if case["unknown"]:
        assert human == case["input"]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda case: case["name"])
def test_all_stream_boundaries(case):
    content = case["input"]
    for split in range(len(content) + 1):
        stream = CitationStreamFilter(CLUES)
        actual = stream.feed(content[:split]) + stream.feed(content[split:]) + stream.finish()
        assert actual.strip() == case["ai"].strip(), (split, actual)
    stream = CitationStreamFilter(CLUES)
    actual = "".join(stream.feed(char) for char in content) + stream.finish()
    assert actual.strip() == case["ai"].strip()


def test_long_reason_does_not_activate_partial_or_unknown_group():
    text = "[" + "一段推理" * 450 + "][c01,c99]"
    stream = CitationStreamFilter(CLUES)
    result = (
        "".join(stream.feed(text[i : i + 37]) for i in range(0, len(text), 37)) + stream.finish()
    )
    assert result == parse_clue_citations(text, CLUES, strip_unknown=True)[0]


def test_speech_and_incomplete_reference():
    assert speech_text("[c01]：[推理文字][c01,c02]", CLUES, ["c01", "c02"]) == "门锁材料：推理文字"
    stream = CitationStreamFilter(CLUES)
    assert stream.feed("正文[推理][c01") == "正文"
    assert stream.finish() == "[推理][c01"


def test_deep_brackets_do_not_exhaust_python_stack_or_swallow_following_tags():
    text = "[" * 1050 + "[c01]" + "]" * 1050 + "。后续[c02]"
    _, refs, unknown = parse_clue_citations(text, CLUES, strip_unknown=True)
    assert refs == ["c01", "c02"]
    assert unknown == []
