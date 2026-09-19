"""Opt-in, bounded multi-model citation evaluation using public fictional cases."""

import argparse
import asyncio
import hashlib
import json
import os
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path


def check_output(raw, clues, streamed, *, require_direct=False, min_evidence=1, required_ids=()):
    import re

    from app.game.citation_syntax import tokenize
    from app.game.clues import parse_clue_citations

    normalized, refs, unknown = parse_clue_citations(raw, clues, strip_unknown=True)
    tokens = tokenize(raw)
    bare_group = re.compile(r"\[c\d{2,4}(?:[,，、;；\s]+c\d{2,4})+\]", re.I)
    return {
        "nonempty": bool(raw.strip()),
        "direct": not require_direct or any(t.ids and t.label is None for t in tokens),
        "attached": any(t.label and t.ids and len(t.ids) >= min_evidence for t in tokens),
        "well_formed_groups": not any(
            t.label is None and bare_group.fullmatch(t.raw) for t in tokens
        ),
        "required_evidence": set(required_ids).issubset(refs),
        "only_revealed": not unknown,
        "stream_matches": streamed.strip() == normalized.strip(),
    }, refs


async def run(args):
    from dotenv import load_dotenv

    if args.env_file:
        load_dotenv(args.env_file, override=False)
    if args.backend:
        os.environ["INFERENCE_BACKEND"] = args.backend

    from langchain.agents.middleware.types import ModelRequest
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    from app.agents.agent_prompts import build_role_system_prompt
    from app.agents.game_model_paths import create_game_model, visible_speech_text
    from app.agents.stage_policy import StagePolicyMiddleware
    from app.core.config import settings
    from app.core.inference import InferenceScope, gateway_model, inference_scope
    from app.core.model_registry import get_model_spec
    from app.game.citation_stream import CitationStreamFilter

    fixtures = json.loads(args.cases.read_text(encoding="utf-8"))
    specs = [get_model_spec(model) for model in args.models]
    jobs = [
        (spec, case, repeat)
        for spec in specs
        for repeat in range(1, (1 if spec.tier == "frontier" else args.repeats) + 1)
        for case in fixtures["cases"][: 1 if spec.tier == "frontier" else 3]
    ]
    if len(jobs) > 40:
        raise ValueError("At most 40 calls per explicit evaluation run")
    result = {
        "at": datetime.now(UTC).isoformat(),
        "backend": settings.INFERENCE_BACKEND,
        "planned_calls": len(jobs),
        "rows": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(2)
    key = os.environ.get(args.gateway_key_env, "")
    if settings.INFERENCE_BACKEND == "tokendance" and not key:
        raise ValueError("The selected gateway key environment variable is not configured")
    scope = InferenceScope(
        "citation-evaluation",
        lambda: key,
        allowed_models=frozenset(gateway_model(spec.id) for spec in specs),
    )

    async def evaluate(spec, case, repeat):
        async with semaphore:
            clues = [clue for clue in fixtures["clues"] if clue["stage"] <= case["round"]]
            model = create_game_model(spec.id, "speech", timeout=120, max_retries=0)
            history = [AIMessage(content=text) for text in case.get("history", [])]
            request = StagePolicyMiddleware().prepare(
                ModelRequest(
                    model=model,
                    tools=[],
                    system_message=SystemMessage(
                        content=build_role_system_prompt(
                            "你是值班记录员沈砚。冷静、谨慎，只讨论已经知道的事实。",
                            "你是本次讨论的记录员。尚不知道是谁进入了房间，也没有额外私人证据。",
                            False,
                        )
                    ),
                    messages=[*history, HumanMessage(content=case["prompt"])],
                    state={"current_stage": "free_discussion", "public_clues": clues},
                )
            )
            payload = [request.system_message, *request.messages]
            row = {
                "model": spec.id,
                "tier": spec.tier,
                "case": case["id"],
                "repeat": repeat,
                "temperature": model.temperature,
                "prompt_sha256": hashlib.sha256(
                    str([m.content for m in payload]).encode()
                ).hexdigest(),
            }
            raw = visible = ""
            stream = CitationStreamFilter(clues)
            started = time.perf_counter()
            try:
                with (
                    inference_scope(scope)
                    if settings.INFERENCE_BACKEND == "tokendance"
                    else nullcontext()
                ):
                    async with asyncio.timeout(125):
                        async for chunk in model.astream(payload):
                            for text in visible_speech_text(chunk):
                                raw += text
                                visible += stream.feed(text)
                            if chunk.usage_metadata:
                                row["usage"] = chunk.usage_metadata
                visible += stream.finish()
                checks, refs = check_output(
                    raw,
                    clues,
                    visible,
                    require_direct=case.get("require_direct", False),
                    min_evidence=case.get("min_evidence", 1),
                    required_ids=case.get("required_ids", []),
                )
                row.update(
                    status="pass" if all(checks.values()) else "format_failure",
                    checks=checks,
                    refs=refs,
                    raw=raw,
                    rendered=visible,
                )
            except Exception as error:
                row.update(
                    status="transport_error",
                    error_type=type(error).__name__,
                    status_code=getattr(error, "status_code", None),
                )
            row["elapsed_seconds"] = round(time.perf_counter() - started, 2)
            result["rows"].append(row)
            args.output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                json.dumps(
                    {k: row[k] for k in ("model", "case", "repeat", "status", "elapsed_seconds")},
                    ensure_ascii=False,
                ),
                flush=True,
            )

    await asyncio.gather(*(evaluate(*job) for job in jobs))
    if any(row["status"] != "pass" for row in result["rows"]):
        raise SystemExit("Evaluation contains failures; inspect the saved report")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("../fixtures/clue-citation-eval.json"))
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--repeats", type=int, choices=(1, 2), default=1)
    parser.add_argument("--backend", choices=("direct", "tokendance"))
    parser.add_argument("--gateway-key-env", default="TOKENDANCE_API_KEY")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
