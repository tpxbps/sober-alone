from app.game.citation_stream import CitationStreamFilter
from scripts.clue_citation_eval import check_output

CLUES = [
    {"id": "c01", "summary": "门锁", "content": "完好", "stage": 1},
    {"id": "c02", "summary": "窗台", "content": "有泥", "stage": 1},
]


def evaluate(raw, **kwargs):
    stream = CitationStreamFilter(CLUES)
    rendered = "".join(stream.feed(character) for character in raw) + stream.finish()
    checks, _ = check_output(raw, CLUES, rendered, **kwargs)
    return checks, rendered


def test_separate_claims_can_each_cite_one_of_two_required_sources():
    checks, _ = evaluate("[门完好][c01]。[窗有泥][c02]。", required_ids=["c01", "c02"])
    assert all(checks.values())


def test_malformed_model_list_is_a_failure_even_when_host_degrades_readably():
    checks, rendered = evaluate("[推理][c01]再看[c01,c02]")
    assert not checks["well_formed_groups"]
    assert checks["stream_matches"]
    assert rendered == "[推理][c01]再看[c01][c02]"


def test_unknown_model_reference_is_a_failure_even_when_host_strips_it():
    checks, rendered = evaluate("[推理][c01,c99]")
    assert not checks["only_revealed"]
    assert rendered == "[推理][c01]"
