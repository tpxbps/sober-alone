from app.services.game_presenter import GameStatePresenter


def test_presenter_only_discloses_private_script_to_human_character():
    characters = [
        {
            "character_id": "human",
            "name": "甲",
            "character_script": "甲的完整个人剧本",
            "system_prompt": "甲的系统提示",
        },
        {
            "character_id": "ai",
            "name": "乙",
            "character_script": "乙的完整个人剧本",
            "system_prompt": "乙的系统提示",
        },
    ]

    presented = GameStatePresenter.characters(characters, "human")

    assert presented[0]["character_script"] == "甲的完整个人剧本"
    assert presented[0]["system_prompt"] == "甲的系统提示"
    assert presented[1]["character_script"] is None
    assert presented[1]["system_prompt"] is None
