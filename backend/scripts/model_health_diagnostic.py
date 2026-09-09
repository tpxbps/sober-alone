"""Explicit paid diagnostic; reports metadata only and never logs credentials/content."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
import warnings
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.reaction import (
    SpeechReactionPayload,
    build_reaction_analysis_prompt,
    build_reaction_system_prompt,
)
from app.core.config import settings
from app.core.llm_factory import create_llm
from app.core.model_registry import get_model_spec
from app.services import model_health as health

CASES = [
    ("timeline", health._REACTION_PROBE_SPEECH),
    (
        "direct_accusation",
        "林岚，我21:48看到你从设备柜旁离开，你说没看清谁动过录音笔，可钥匙一直在你手里。我怀疑你拿走了R-07，请解释。",
    ),
    (
        "no_accusation",
        "我补充一个已确认的时间：21:39服务器停止运行。现在还不知道谁碰过设备柜，先请大家各自核对时间，不要急着指认任何人。",
    ),
]


async def run(args):
    if hasattr(settings, "ANALYTICS_ENABLED"):
        settings.ANALYTICS_ENABLED = False
    logging.disable(logging.CRITICAL)
    warnings.filterwarnings("ignore", message="Cannot use method='json_schema'.*")
    rows = []
    for repeat in range(args.repeats):
        for index, (case_id, speech) in enumerate(CASES[: args.cases]):
            variants = (
                args.variants[index % len(args.variants) :]
                + args.variants[: index % len(args.variants)]
            )
            for variant in variants:
                llm = create_llm(
                    model=args.model,
                    temperature=args.temperature,
                    timeout=int(args.timeout),
                    max_retries=0,
                    disable_thinking=True,
                )
                if variant in {"disabled_schema", "disabled_json"}:
                    llm = llm.model_copy(update={"extra_body": {"thinking": {"type": "disabled"}}})
                elif variant in {"default_schema", "default_json"}:
                    llm = llm.model_copy(update={"extra_body": None})
                if variant.startswith("low_"):
                    llm = llm.model_copy(update={"extra_body": None, "reasoning_effort": "low"})
                method = (
                    get_model_spec(args.model).reaction_output_method
                    if variant == "configured"
                    else ("json_mode" if variant.endswith("json") else "json_schema")
                )
                structured = llm.with_structured_output(
                    SpeechReactionPayload, method=method, include_raw=True
                )
                messages = [
                    SystemMessage(
                        content=build_reaction_system_prompt(
                            health._REACTION_PROBE_ROLE, health._REACTION_PROBE_SCRIPT
                        )
                    ),
                    HumanMessage(
                        content=build_reaction_analysis_prompt(
                            "林岚", health._REACTION_PROBE_SPEAKER, speech
                        )
                    ),
                ]
                row = {
                    "model": args.model,
                    "variant": variant,
                    "case": case_id,
                    "repeat": repeat + 1,
                    "at": datetime.now(UTC).isoformat(),
                    "timeout_seconds": args.timeout,
                    "temperature": args.temperature,
                }
                started = time.perf_counter()
                try:
                    async with asyncio.timeout(args.timeout):
                        result = await structured.ainvoke(messages)
                    raw = result["raw"]
                    row.update(
                        output_chars=len(str(raw.content)),
                        reasoning_chars=len(
                            str(raw.additional_kwargs.get("reasoning_content") or "")
                        ),
                        usage=raw.usage_metadata,
                        finish_reason=raw.response_metadata.get("finish_reason"),
                    )
                    if result.get("parsing_error"):
                        raise result["parsing_error"]
                    parsed = SpeechReactionPayload.model_validate(result["parsed"])
                    parsed.to_reaction()
                    row.update(
                        status="ok",
                        suspicion_count=len(parsed.suspicion_changes),
                        suspected_by_count=len(parsed.suspected_by_changes),
                        perspective_chars=len(parsed.main_perspective),
                    )
                    row["case_checks_pass"] = bool(parsed.main_perspective) and (
                        case_id != "direct_accusation"
                        or any(
                            item.suspecter == health._REACTION_PROBE_SPEAKER and item.need_response
                            for item in parsed.suspected_by_changes
                        )
                    )
                except Exception as exc:
                    row.update(
                        status="timeout" if isinstance(exc, TimeoutError) else "error",
                        error_type=type(exc).__name__,
                        status_code=getattr(exc, "status_code", None),
                    )
                    detail = str(getattr(exc, "body", "") or type(exc).__name__)
                    for provider in (
                        "deepseek",
                        "stepfun",
                        "alibaba",
                        "bytedance",
                        "mimo",
                        "hunyuan",
                        "zhipuai",
                    ):
                        key = settings.get_api_key(provider)
                        if key:
                            detail = detail.replace(key, "[REDACTED]")
                    row["error_detail"] = detail[:1200]
                    if hasattr(exc, "errors"):
                        row["validation_errors"] = [
                            {"type": e["type"], "loc": e["loc"]}
                            for e in exc.errors(include_input=False)
                        ]
                row["elapsed_seconds"] = round(time.perf_counter() - started, 3)
                rows.append(row)
                Path(args.output).write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="glm-5.3-flash")
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["default_schema", "disabled_schema", "disabled_json", "default_json"],
    )
    parser.add_argument("--cases", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--timeout", type=float, default=75)
    parser.add_argument("--output", default=".local-data/model-health-diagnostic.json")
    asyncio.run(run(parser.parse_args()))
