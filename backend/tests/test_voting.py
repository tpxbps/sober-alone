from app.services.voting import VotingService


def test_vote_summary_preserves_tie_and_counts_abstention_in_turnout():
    votes = {
        "voter-a": {"suspect_id": "suspect-a", "suspect_name": "甲"},
        "voter-b": {"suspect_id": "suspect-b", "suspect_name": "乙"},
        "voter-c": {"suspect_id": None, "suspect_name": "弃票"},
    }

    result = VotingService.summarize(votes)

    assert result["vote_count"] == {"suspect-a": 1, "suspect-b": 1}
    assert result["total_votes"] == 3
    assert result["final_suspect"] == "suspect-a"
    assert result["final_suspect_votes"] == 1
    assert result["tied_suspects"] == ["suspect-a", "suspect-b"]


def test_vote_summary_with_only_abstentions_has_no_suspect():
    result = VotingService.summarize({"voter": {"suspect_id": None, "suspect_name": "弃票"}})

    assert result["vote_count"] == {}
    assert result["total_votes"] == 1
    assert result["final_suspect"] is None
    assert result["tied_suspects"] == []
