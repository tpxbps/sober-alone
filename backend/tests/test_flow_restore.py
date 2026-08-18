import pytest

from app.db.models import GameSession, GameStage
from app.game.flow_controller import GameFlowController

PROCESS = [
    {"type": "initial"},
    {"type": "advancement", "children": [{}, {}]},
    {"type": "advancement", "children": [{}, {}]},
    {"type": "vote", "children": [{}, {}]},
    {"type": "review"},
]


@pytest.mark.parametrize(
    ("stage", "round_num", "expected"),
    [
        (GameStage.INTRO.value, 0, (0, 0)),
        (GameStage.CLUE_ANALYSIS.value, 1, (1, 0)),
        (GameStage.FREE_DISCUSSION.value, 1, (1, 1)),
        (GameStage.CLUE_ANALYSIS.value, 2, (2, 0)),
        (GameStage.FREE_DISCUSSION.value, 2, (2, 1)),
        (GameStage.SUMMARY.value, 3, (3, 0)),
        (GameStage.VOTE.value, 3, (3, 1)),
        (GameStage.REVIEW.value, 4, (4, 0)),
        (GameStage.COMPLETED.value, 4, (4, 0)),
    ],
)
def test_restart_restores_process_cursor(stage, round_num, expected):
    session = GameSession(
        session_id="session",
        script_id="script",
        current_stage=stage,
        current_round=round_num,
    )

    controller = GameFlowController(session, {"game_full_process": PROCESS}, object())

    assert (controller.current_process_index, controller.current_child_index) == expected
