"""Opt-in paid citation smoke; never collected by pytest. Outputs stay in a private directory."""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


async def run(args):
    if args.env_file:
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=False)
    from langchain_core.messages import HumanMessage, SystemMessage

    from app.agents.stage_policy import stage_instructions
    from app.core.llm_factory import create_llm
    from app.game.citation_stream import CitationStreamFilter
    from app.game.citation_syntax import tokenize
    from app.game.clues import normalize_clue_stages, parse_clue_citations
    from app.game.content_quality import content_fingerprint

    source = json.loads(args.source.read_text(encoding="utf-8-sig"))
    stages = normalize_clue_stages(source["clue_stages"], script_id=source["script_id"])
    model = create_llm(
        model=args.model,
        temperature=args.temperature,
        timeout=90,
        max_retries=0,
        disable_thinking=True,
    )
    result = {
        "model": args.model,
        "temperature": args.temperature,
        "repeats": args.repeats,
        "content_fingerprint": content_fingerprint(source),
        "time": datetime.now(timezone.utc).isoformat(),
        "rounds": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for attempt, stage in (
        (attempt, stage) for attempt in range(1, args.repeats + 1) for stage in stages
    ):
        clues = [
            clue for item in stages if item["stage"] <= stage["stage"] for clue in item["items"]
        ]
        instructions = stage_instructions({"current_stage": "clue_analysis", "public_clues": clues})
        stream = CitationStreamFilter(clues)
        raw, visible = "", ""
        async for chunk in model.astream(
            [
                SystemMessage(
                    content="你在进行公开线索推理，只能依据已公开的资料。\n" + instructions
                ),
                HumanMessage(
                    content="请用两三句话提出一个待核实的判断：先用直接点名格式讨论一条线索，再用关联引用格式为一段推理附上至少两条证据。不要给出投票答案。只输出发言，不调用工具。"
                ),
            ]
        ):
            if isinstance(chunk.content, str):
                raw += chunk.content
                visible += stream.feed(chunk.content)
        visible += stream.finish()
        normalized, refs, unknown = parse_clue_citations(raw, clues, strip_unknown=True)
        tokens = tokenize(raw)
        checks = {
            "direct": any(token.ids and token.label is None for token in tokens),
            "attached_multiple": any(
                token.ids and token.label and len(token.ids) >= 2 for token in tokens
            ),
            "only_revealed": not unknown,
            "stream_matches": visible.strip() == normalized.strip(),
        }
        result["rounds"].append(
            {
                "stage": stage["stage"],
                "attempt": attempt,
                "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                "checks": checks,
                "raw": raw,
                "rendered": visible,
                "refs": refs,
            }
        )
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {"attempt": attempt, "stage": stage["stage"], "checks": checks}, ensure_ascii=False
            ),
            flush=True,
        )
    if not all(all(item["checks"].values()) for item in result["rounds"]):
        raise SystemExit("Citation smoke requires review")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
