"""Opt-in TokenDance gameplay comparison, with conservative reservations and actual bills.

Results require semantic review against each case's criteria. No keyword-based grading.
Candidate registration is process-local and never makes an unqualified model selectable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
import uuid
from pathlib import Path


class BillingBudget:
    def __init__(self, key, limit, ledger):
        import httpx

        self.client = httpx.AsyncClient(
            base_url="https://tokendance.space",
            headers={"Authorization": "Bearer " + key},
            timeout=30,
        )
        self.limit = limit * 1_000_000
        self.ledger = ledger
        self.data = (
            json.loads(ledger.read_text())
            if ledger.exists()
            else {
                "app_url": "https://example.invalid/gameplay-eval/" + uuid.uuid4().hex,
                "bills": [],
                "pending_micro_rmb": 0,
                "requests": 0,
            }
        )

    def save(self):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.ledger.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    async def reconcile(self):
        # Include all paginated records: live application calls may share this account.
        bills = {}
        cursor = self.data.get("start_id")
        end = None
        while True:
            await asyncio.sleep(1.05)
            params = {"limit": 500}
            if cursor:
                params["start_id"] = cursor
            if end:
                params["end_id"] = end
            response = await self.client.get("/portal/api/v1/usage", params=params)
            response.raise_for_status()
            items = response.json()["items"]
            if "start_id" not in self.data:
                self.data["start_id"] = items[0]["id"] if items else "0"
                self.save()
                return
            for item in items:
                if item.get("app_url", "").rstrip("/") == self.data["app_url"].rstrip("/"):
                    bills[item["id"]] = item
            if len(items) < 500:
                break
            end = items[-1]["id"]
        self.data["bills"] = list(bills.values())
        if len(bills) == self.data["requests"]:
            self.data["pending_micro_rmb"] = 0
        self.save()

    async def settle(self):
        for _ in range(8):
            await self.reconcile()
            if len(self.data["bills"]) == self.data["requests"]:
                return
            await asyncio.sleep(2)
        raise RuntimeError("Billing incomplete; stop dispatch until remaining budget is known")

    async def reserve(self, model_slug, payload, max_output):
        await self.settle()
        response = await self.client.get("/portal/api/models/" + model_slug)
        response.raise_for_status()
        pricing = response.json()["pricing"]
        rates = {"input_tokens": [], "completion_tokens": []}

        def visit(node):
            if isinstance(node, dict):
                name = node.get("id", "")
                for kind in rates:
                    if name == "openai:chat-completions:" + kind:
                        for plan in node["plans"]:
                            if plan["unit"] != "millionTokens":
                                raise ValueError("Unsupported pricing unit")
                            rates[kind].append(float(plan["rate"]))
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(pricing)
        if not all(rates.values()):
            raise RuntimeError("Cannot establish maximum input/output prices")
        # UTF-8 bytes upper-bound text tokens; overhead covers message wrappers and schemas.
        input_bound = len(json.dumps(payload, ensure_ascii=False).encode()) + 4096
        reserve = math.ceil(
            input_bound * max(rates["input_tokens"]) + max_output * max(rates["completion_tokens"])
        )
        paid = sum(b["cost"] for b in self.data["bills"])
        if paid + reserve > self.limit:
            raise RuntimeError("Evaluation budget exhausted before dispatch")
        self.data["pending_micro_rmb"] = reserve
        self.data["requests"] += 1
        self.save()


async def run(args):
    from dotenv import load_dotenv

    if args.env_file:
        load_dotenv(args.env_file, override=False)
    os.environ["INFERENCE_BACKEND"] = "tokendance"
    key = os.environ[args.key_env]
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agents.agent_player import AgentPlayer
    from app.agents.agent_prompts import build_role_system_prompt
    from app.agents.game_model_paths import (
        build_role_agent,
        create_game_model,
        visible_role_speech_text,
    )
    from app.agents.reaction import (
        SpeechReactionPayload,
        build_reaction_analysis_prompt,
        build_reaction_system_prompt,
    )
    from app.core.config import settings
    from app.core.inference import InferenceScope, gateway_model, inference_scope
    from app.core.model_registry import MODEL_BY_ID, ModelSpec

    MODEL_BY_ID["mimo-v2.6-flash"] = ModelSpec(
        "mimo-v2.6-flash",
        "MiMo V2.6 Flash",
        "mimo",
        "Xiaomi MiMo",
        backends=("tokendance",),
        reaction_output_method="json_mode",
    )
    fixtures = json.loads(args.cases.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    budget = BillingBudget(key, args.budget, args.ledger)
    await budget.reconcile()
    settings.TOKENDANCE_APP_URL = budget.data["app_url"]
    scope = InferenceScope(
        "gameplay-evaluation",
        lambda: key,
        allowed_models=frozenset(gateway_model(m) for m in args.models),
    )
    rows = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else []
    completed = {(r["model"], r["case"], r["repeat"], r["purpose"]) for r in rows}
    baseline = (
        json.loads(args.prompt_baseline.read_text(encoding="utf-8"))
        if args.prompt_baseline
        else None
    )

    def save():
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    with inference_scope(scope):
        for repeat in range(1, args.repeats + 1):
            for case in fixtures["cases"]:
                if args.case_ids and case["id"] not in args.case_ids:
                    continue
                role = f"你是{case['role']}，按自己的经历和目标行动。"
                overviews = (
                    [] if args.omit_overviews else [{"stage": 1, "content": case["overview"]}]
                )
                state = {
                    "current_stage": case["stage"],
                    "public_clues": case["items"],
                    "public_round_overviews": overviews,
                }
                for model_id in args.models:
                    for purpose in ("speech", "reaction"):
                        identity = (model_id, case["id"], repeat, purpose)
                        if identity in completed:
                            continue
                        model = create_game_model(model_id, purpose, timeout=90, max_retries=0)
                        extra = model.extra_body
                        if model_id == "mimo-v2.6-flash":
                            extra = {
                                "thinking": {"type": "enabled" if args.thinking else "disabled"}
                            }
                        model = model.model_copy(
                            update={"max_tokens": args.max_output, "extra_body": extra}
                        )
                        if purpose == "speech":
                            system = build_role_system_prompt(role, case["private"], False)
                            if baseline:
                                system = baseline[case["id"]]["speech"]
                            stage_prompt = (
                                baseline[case["id"]]["stage"]
                                if baseline
                                else AgentPlayer._get_stage_prompt(None, case["stage"])
                            )
                            messages = [
                                SystemMessage(content=system),
                                HumanMessage(
                                    content=stage_prompt
                                    + "\n"
                                    + "\n".join(
                                        case["history"]
                                        + [case["speaker"] + "：" + case["utterance"]]
                                    )
                                ),
                            ]
                        else:
                            system = build_reaction_system_prompt(role, case["private"])
                            if baseline:
                                system = baseline[case["id"]]["reaction"]
                            messages = [
                                SystemMessage(content=system),
                                HumanMessage(
                                    content=build_reaction_analysis_prompt(
                                        case["role"],
                                        case["speaker"],
                                        case["utterance"],
                                        public_clues=case["items"],
                                        public_round_overviews=overviews,
                                        current_state=case.get("current_state"),
                                        character_names=fixtures["characters"],
                                    )
                                ),
                            ]
                        schema = SpeechReactionPayload.model_json_schema()
                        if purpose == "reaction":
                            await budget.reserve(
                                gateway_model(model_id),
                                [m.content for m in messages] + [schema],
                                args.max_output,
                            )
                        row = dict(
                            zip(("model", "case", "repeat", "purpose"), identity, strict=True)
                        )
                        row.update(
                            criteria=case["criteria"], thinking=args.thinking, semantic_review=None
                        )
                        started = time.perf_counter()
                        billing_seconds = 0.0
                        try:
                            if purpose == "speech":

                                class BudgetMiddleware(AgentMiddleware):
                                    async def awrap_model_call(self, request, handler):
                                        nonlocal billing_seconds
                                        before = time.perf_counter()
                                        await budget.reserve(
                                            gateway_model(model_id),
                                            [
                                                str(request.system_message),
                                                *[str(m) for m in request.messages],
                                                *[
                                                    t.args_schema.model_json_schema()
                                                    for t in request.tools
                                                ],
                                            ],
                                            args.max_output,
                                        )
                                        billing_seconds += time.perf_counter() - before
                                        try:
                                            return await handler(request)
                                        finally:
                                            before = time.perf_counter()
                                            await budget.settle()
                                            billing_seconds += time.perf_counter() - before

                                agent = build_role_agent(
                                    model,
                                    model,
                                    system_prompt=system,
                                    rag_enabled=False,
                                    checkpointer=None,
                                    middleware=[BudgetMiddleware()],
                                )
                                input_state = {
                                    **state,
                                    "messages": messages[1:],
                                    "current_round": 1,
                                    "session_id": "synthetic-eval",
                                    "script_id": "synthetic-eval",
                                    "character_id": "role-0",
                                    "character_name": case["role"],
                                    "character_names": fixtures["characters"],
                                    "character_name_map": {
                                        f"role-{i}": n for i, n in enumerate(fixtures["characters"])
                                    },
                                }
                                output = ""
                                async for token, metadata in agent.astream(
                                    input_state,
                                    config={"recursion_limit": 10},
                                    stream_mode="messages",
                                ):
                                    visible = "".join(visible_role_speech_text(token, metadata))
                                    if visible and "ttft" not in row:
                                        row["ttft"] = (
                                            time.perf_counter() - started - billing_seconds
                                        )
                                    output += visible
                                row["output"] = output
                            else:
                                method = (
                                    "json_mode"
                                    if model_id == "mimo-v2.6-flash"
                                    else "function_calling"
                                )
                                response = await model.with_structured_output(
                                    SpeechReactionPayload, method=method, include_raw=True
                                ).ainvoke(messages)
                                row["raw"] = str(
                                    response["raw"].content or response["raw"].tool_calls
                                )
                                if response["parsing_error"]:
                                    raise ValueError("Structured reaction validation failed")
                                result = response["parsed"]
                                row["output"] = result.model_dump()
                                targets = [r.target for r in result.suspicion_changes] + [
                                    r.suspecter for r in result.suspected_by_changes
                                ]
                                row["legal_names"] = all(
                                    t in fixtures["characters"] and t != case["role"]
                                    for t in targets
                                )
                        except Exception as exc:
                            row["error"] = type(exc).__name__
                        row["elapsed"] = time.perf_counter() - started - billing_seconds
                        rows.append(row)
                        save()
                        await budget.settle()
                        print(
                            json.dumps(
                                {
                                    "model": model_id,
                                    "case": case["id"],
                                    "repeat": repeat,
                                    "purpose": purpose,
                                    "elapsed": round(row["elapsed"], 2),
                                    "error": row.get("error"),
                                    "paid_rmb": sum(b["cost"] for b in budget.data["bills"])
                                    / 1_000_000,
                                }
                            ),
                            flush=True,
                        )
    await budget.client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["mimo-v2.6-flash", "deepseek-flash"])
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "fixtures/gameplay-eval.json",
    )
    parser.add_argument("--case-ids", nargs="+")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--key-env", default="TOKENDANCE_API_KEY")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--budget", type=float, required=True)
    parser.add_argument("--max-output", type=int, default=4096)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--omit-overviews", action="store_true")
    parser.add_argument("--prompt-baseline", type=Path)
    args = parser.parse_args()
    if (
        not 0 < args.budget <= 10
        or not 1 <= args.repeats <= 3
        or not 256 <= args.max_output <= 16384
    ):
        parser.error("budget must be (0,10], repeats 1..3, max-output 256..16384")
    asyncio.run(run(args))
