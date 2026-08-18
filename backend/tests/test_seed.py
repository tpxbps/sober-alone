from app.seed import (
    CHARACTERS,
    FULL_TRUTH,
    ROUND_ONE_CLUES,
    ROUND_TWO_CLUES,
    SAMPLE_SCRIPT_ID,
    SAMPLE_TITLE,
    STORY_BACKGROUND,
    _game_process,
)


def test_sample_has_a_complete_two_round_mystery_structure():
    process = _game_process()

    assert SAMPLE_SCRIPT_ID == "sample-midnight-call-v1"
    assert SAMPLE_TITLE == "零点来电"
    assert [stage["type"] for stage in process] == [
        "initial",
        "advancement",
        "advancement",
        "vote",
        "review",
    ]
    assert process[0]["system_notice"] == STORY_BACKGROUND
    assert process[1]["children"][0]["system_notice"] == ROUND_ONE_CLUES
    assert process[2]["children"][0]["system_notice"] == ROUND_TWO_CLUES
    assert process[-1]["system_notice"] == FULL_TRUTH


def test_sample_characters_are_distinct_and_have_staged_private_scripts():
    character_ids = {character["character_id"] for character in CHARACTERS}
    character_names = {character["name"] for character in CHARACTERS}

    assert len(CHARACTERS) == 4
    assert len(character_ids) == 4
    assert character_names == {"姜芮", "陆鸣", "陈朔", "许棠"}
    assert all(len(character["character_script"]) >= 900 for character in CHARACTERS)
    assert all(len(character["system_prompt"]) >= 250 for character in CHARACTERS)
    assert all("第一轮" in character["system_prompt"] for character in CHARACTERS)
    assert all("第二轮" in character["system_prompt"] for character in CHARACTERS)

    killer = next(character for character in CHARACTERS if character["name"] == "姜芮")
    assert "你是凶手" in killer["character_script"]
    assert "导致梁序死亡并伪造广播" in killer["system_prompt"]
    assert "21:44" in killer["character_script"]


def test_sample_truth_closes_the_false_broadcast_and_every_red_herring():
    assert len(FULL_TRUTH) >= 1100
    for fact in ("21:44", "21:55", "自动播出队列", "陆鸣", "陈朔", "许棠", "姜芮"):
        assert fact in FULL_TRUTH
