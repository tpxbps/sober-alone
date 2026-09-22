import json

from app.seed import CHARACTERS, SAMPLE_DATA, SAMPLE_SCRIPT_ID, _game_process, _sample_clue_stages


def test_sample_has_a_complete_text_only_structure():
    assert SAMPLE_SCRIPT_ID == "sample-best-partners-v1"
    assert [stage["type"] for stage in _game_process()] == [
        "initial",
        "advancement",
        "advancement",
        "vote",
        "review",
    ]
    stages = _sample_clue_stages()
    assert [len(stage["items"]) for stage in stages] == [6, 7]
    assert len({item["id"] for stage in stages for item in stage["items"]}) == 13
    assert SAMPLE_DATA["full_truth"]
    assert len(CHARACTERS) == 4
    assert len({c["character_id"] for c in CHARACTERS}) == 4
    assert all(c["character_script"] and c["system_prompt"] for c in CHARACTERS)


def test_sample_contains_no_online_identity_or_media_metadata():
    forbidden = {
        "owner_uuid",
        "created_at",
        "updated_at",
        "review",
        "quality_report",
        "voice_id",
        "avatar_url",
        "portrait_url",
        "image_url",
        "audio_url",
        "presentation",
        "stage_presentation",
        "cover_image_url",
    }

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value)
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)

    check(SAMPLE_DATA)
    assert "https://" not in json.dumps(SAMPLE_DATA)


def test_seed_helpers_do_not_mutate_the_embedded_source():
    process = _game_process()
    process[0]["system_notice"] = "changed"
    stages = _sample_clue_stages()
    stages[0]["overview"] = "changed"
    assert _game_process()[0]["system_notice"] != "changed"
    assert _sample_clue_stages()[0]["overview"] != "changed"
