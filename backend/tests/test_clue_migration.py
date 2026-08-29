from app.db.models import Script
from app.script_editor.clue_migration import _digest, _legacy_payload


def test_legacy_migration_keeps_clue_facts_and_discussion_guidance_separate():
    script = Script(
        script_id="legacy",
        title="旧剧本",
        game_full_process=[
            {
                "type": "advancement",
                "children": [
                    {"system_notice": "门锁没有撬动痕迹。\n\n请结合时间线讨论。"},
                    {"system_notice": "每人还可发言一次。"},
                ],
            }
        ],
    )

    payload = _legacy_payload(script)

    assert payload == [
        {
            "stage": 1,
            "clue_text": "门锁没有撬动痕迹。",
            "free_discussion_notice": "请结合时间线讨论。\n\n每人还可发言一次。",
        }
    ]
    assert _digest(payload) == _digest(payload)
