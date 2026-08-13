"""Voting result presentation kept independent from transport and agent execution."""

from __future__ import annotations

from typing import Any


class VotingService:
    """Pure vote aggregation used by the GameService façade."""

    @staticmethod
    def summarize(votes: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
        if not votes:
            return {}

        vote_count: dict[str, int] = {}
        for vote_info in votes.values():
            suspect_id = vote_info.get("suspect_id")
            if suspect_id:
                vote_count[suspect_id] = vote_count.get(suspect_id, 0) + 1

        max_votes = max(vote_count.values(), default=0)
        tied_suspects = [
            suspect_id
            for suspect_id, count in vote_count.items()
            if max_votes > 0 and count == max_votes
        ]

        return {
            "vote_count": vote_count,
            "total_votes": len(votes),
            "final_suspect": tied_suspects[0] if tied_suspects else None,
            "final_suspect_votes": max_votes,
            "tied_suspects": tied_suspects,
            "details": votes,
        }
