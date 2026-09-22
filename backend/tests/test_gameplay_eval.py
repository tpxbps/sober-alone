import json
from pathlib import Path

import pytest

from scripts.gameplay_eval import BillingBudget


def test_gameplay_cases_have_semantic_criteria_and_public_fictional_inputs():
    path = Path(__file__).resolve().parents[2] / "fixtures/gameplay-eval.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert len(fixture["cases"]) == 12
    assert len({c["id"] for c in fixture["cases"]}) == 12
    assert all(c["criteria"] and c["private"] and c["overview"] for c in fixture["cases"])


@pytest.mark.asyncio
async def test_budget_reserves_peak_prices_and_stops_before_overspending(tmp_path, monkeypatch):
    budget = BillingBudget("synthetic", 0.01, tmp_path / "ledger.json")
    await budget.client.aclose()

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "pricing": {
                    "items": [
                        {
                            "id": "openai:chat-completions:input_tokens",
                            "plans": [{"unit": "millionTokens", "rate": "1"}],
                        },
                        {
                            "id": "openai:chat-completions:completion_tokens",
                            "plans": [{"unit": "millionTokens", "rate": "2"}],
                        },
                    ],
                    "time_pricing": {
                        "options": [
                            {
                                "items": [
                                    {
                                        "id": "openai:chat-completions:completion_tokens",
                                        "plans": [{"unit": "millionTokens", "rate": "8"}],
                                    },
                                ]
                            }
                        ]
                    },
                }
            }

    class Client:
        async def get(self, *_args, **_kwargs):
            return Response()

    async def settled():
        pass

    budget.client = Client()
    monkeypatch.setattr(budget, "settle", settled)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        await budget.reserve("model", ["test"], 1000)
    assert budget.data["requests"] == 0
    budget.limit = 100_000
    await budget.reserve("model", ["test"], 1000)
    assert budget.data["requests"] == 1
    assert budget.data["pending_micro_rmb"] > 12_000


@pytest.mark.asyncio
async def test_unknown_bill_prevents_following_requests(tmp_path, monkeypatch):
    budget = BillingBudget("synthetic", 10, tmp_path / "ledger.json")
    await budget.client.aclose()
    budget.data["requests"] = 1

    async def no_change(*_args):
        pass

    monkeypatch.setattr(budget, "reconcile", no_change)
    monkeypatch.setattr("scripts.gameplay_eval.asyncio.sleep", no_change)
    with pytest.raises(RuntimeError, match="Billing incomplete"):
        await budget.reserve("model", [], 1000)
    assert budget.data["requests"] == 1
