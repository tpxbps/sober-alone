"""Paid real-model game lifecycle audit using isolated sample data; no production writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path


async def run(args):
    workspace = Path(args.output).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["ANALYTICS_ENABLED"] = "false"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(workspace / 'game.db').as_posix()}"
    os.environ["CHROMA_PERSIST_DIR"] = str(workspace / "chroma")
    from app.core import config

    config.LOCAL_DATA_DIR = workspace
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy import select

    from app import seed
    from app.agents.agent_player import AgentPlayer
    from app.db.base import Base
    from app.db.models import GameRecord, PlayerState
    from app.db.session import AsyncSessionLocal, engine
    from app.services.checkpoint_runtime import set_game_checkpointer
    from app.services.game_service import GameService, ensure_flow_controller, get_flow_controller

    if args.script_file:
        seed.SAMPLE_DATA = json.loads(Path(args.script_file).read_text(encoding="utf-8"))
        seed.SAMPLE_SCRIPT_ID = seed.SAMPLE_DATA["script_id"]
        seed.CHARACTERS = seed.SAMPLE_DATA["characters"]
    characters = seed.CHARACTERS
    human = next((c for c in characters if c["name"] == args.human_character), characters[0])
    if args.human_character and human["name"] != args.human_character:
        raise ValueError("Unknown human character")
    ai_characters = [c for c in characters if c["character_id"] != human["character_id"]]
    if len(args.models) != len(ai_characters):
        raise ValueError("Supply exactly one model for each AI character")
    human_lines = (
        json.loads(Path(args.human_lines).read_text(encoding="utf-8")) if args.human_lines else {}
    )
    vote_target = args.vote_target or characters[0]["name"]
    if vote_target not in {c["name"] for c in characters}:
        raise ValueError("Unknown vote target")
    result = {
        "models": args.models,
        "speech": [],
        "reaction": [],
        "model_errors": [],
        "transitions": [],
        "status": "running",
    }

    def report(event, **data):
        print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)
        (workspace / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.resume:
        result = json.loads((workspace / "result.json").read_text(encoding="utf-8"))
        result["resumed"] = result.get("resumed", 0) + 1
        result.setdefault("model_errors", [])
    original_react = AgentPlayer.react_to_speech

    class ModelErrorCapture(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                result["model_errors"].append(record.getMessage())

    agent_logger = logging.getLogger("app.agents.agent_player")
    agent_logger.setLevel(logging.WARNING)
    agent_logger.addHandler(ModelErrorCapture())

    async def audited_react(self, speaker_name, content, **kwargs):
        started = time.perf_counter()
        response = await original_react(self, speaker_name, content, **kwargs)
        item = {
            "model": self.llm_model,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "perspective_chars": len(response.main_perspective),
            "nonempty": bool(
                response.main_perspective or response.my_suspicion_graph or response.my_suspected_by
            ),
            "valid": (
                self._human_reaction_structured is not None
                if kwargs.get("reaction_context", {}).get("is_human")
                else self._reaction_structured is not None
            ),
        }
        result["reaction"].append(item)
        report("reaction", **item)
        return response

    AgentPlayer.react_to_speech = audited_react
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as db:
        await seed.seed_sample_if_empty(db)
    async with AsyncSqliteSaver.from_conn_string(
        str(workspace / "checkpoints.sqlite")
    ) as checkpointer:
        set_game_checkpointer(checkpointer)
        async with AsyncSessionLocal() as db:
            service = GameService(db)
            human_id = human["character_id"]
            assigned = {
                char["character_id"]: {"model": model}
                for char, model in zip(ai_characters, args.models, strict=True)
            }
            if args.resume:
                sid = result["session_id"]
                flow = await ensure_flow_controller(sid, db)
            else:
                created = await service.create_game(seed.SAMPLE_SCRIPT_ID, human_id, assigned)
                if not created.get("success"):
                    raise RuntimeError("create failed")
                sid = created["session_id"]
                result["session_id"] = sid
                flow = get_flow_controller(sid)
            report("created" if not args.resume else "resumed", models=args.models)
            free_human_stages = set()
            next_speaker = flow.session.current_speaker
            if args.resume and flow.session.current_stage == "free_discussion":
                states = list(
                    (
                        await db.scalars(select(PlayerState).where(PlayerState.session_id == sid))
                    ).all()
                )
                if any(p.character_id == human_id and p.has_spoken_this_round for p in states):
                    free_human_stages.add(flow.session.current_round)
                if all(p.remaining_speech_count == 0 for p in states if p.character_id != human_id):
                    next_speaker = None
            for action in range(100):
                stage = flow.session.current_stage
                round_number = flow.session.current_round
                if stage == "vote":
                    vote = await service.submit_vote(
                        sid,
                        human_id,
                        vote_target,
                        "依据已公开材料与讨论作出判断。",
                    )
                    if not vote.get("success"):
                        raise RuntimeError("human vote failed")
                    final = await service.finalize_voting(sid)
                    if not final.get("success"):
                        raise RuntimeError("finalize failed")
                    states = list(
                        (
                            await db.scalars(
                                select(PlayerState).where(PlayerState.session_id == sid)
                            )
                        ).all()
                    )
                    result["votes"] = [
                        {
                            "id": p.character_id,
                            "has_voted": p.has_voted,
                            "abstained": not p.voted_for,
                        }
                        for p in states
                    ]
                    report(
                        "votes",
                        completed=len(states),
                        abstained=sum(not p.voted_for for p in states),
                    )
                    continue
                if stage in {"review", "completed"}:
                    records = list(
                        (
                            await db.scalars(select(GameRecord).where(GameRecord.session_id == sid))
                        ).all()
                    )
                    result["fallback_records"] = sum(
                        "AI角色出现未知错误" in (r.raw_content or "") for r in records
                    )
                    result["review_persisted"] = any(
                        r.stage == "review" and r.raw_content for r in records
                    )
                    ended = await service.end_game(sid)
                    result["ended"] = ended.get("success", False)
                    result["status"] = (
                        "passed"
                        if result["ended"]
                        and result["review_persisted"]
                        and result["fallback_records"] == 0
                        and not result.get("model_errors")
                        and all(s["chars"] > 0 for s in result["speech"])
                        and all(r["valid"] for r in result["reaction"])
                        and all(not v["abstained"] for v in result["votes"])
                        else "failed"
                    )
                    report(
                        "finished",
                        status=result["status"],
                        speeches=len(result["speech"]),
                        reactions=len(result["reaction"]),
                        fallbacks=result["fallback_records"],
                    )
                    break
                speaker = next_speaker
                if stage == "free_discussion" and round_number not in free_human_stages:
                    speaker = human_id
                    free_human_stages.add(round_number)
                if not speaker:
                    transition = await service.advance_stage(sid)
                    if not transition.get("success"):
                        raise RuntimeError("advance failed")
                    result["transitions"].append(
                        {"from": stage, "to": flow.session.current_stage, "round": round_number}
                    )
                    next_speaker = flow.session.current_speaker
                    report(
                        "stage", stage=flow.session.current_stage, round=flow.session.current_round
                    )
                    continue
                started = time.perf_counter()
                first_token = None
                chars = 0
                events = []
                if speaker == human_id:
                    text = (
                        f"我是{human['name']}。请大家介绍自己和今晚的经历。"
                        if stage == "intro"
                        else "请核对已公开的材料与各自时间线，说明判断的依据和仍有疑问的地方。"
                    )
                    text = human_lines.get(f"{stage}:{round_number}", human_lines.get(stage, text))
                    stream = service.process_human_speech_stream(sid, text)
                else:
                    stream = service.process_ai_speech_stream(sid, speaker)
                async with asyncio.timeout(240):
                    async for payload in stream:
                        event = json.loads(payload.removeprefix("data: ").strip())
                        events.append(event["type"])
                        if event["type"] == "error":
                            raise RuntimeError("SSE error")
                        if event["type"] == "token" and event.get("text"):
                            if first_token is None:
                                first_token = round(time.perf_counter() - started, 3)
                            chars += len(event["text"])
                if not events or events[-1] != "done":
                    raise RuntimeError("SSE did not terminate")
                next_speaker = event.get("next_speaker_id")
                if speaker != human_id:
                    item = {
                        "model": assigned[speaker]["model"],
                        "stage": stage,
                        "round": round_number,
                        "first_token_seconds": first_token,
                        "elapsed_seconds": round(time.perf_counter() - started, 3),
                        "chars": chars,
                    }
                    result["speech"].append(item)
                    report("speech", **item)
                else:
                    report("human", stage=stage, round=round_number)
            else:
                raise RuntimeError("action budget exhausted")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--script-file", help="Authorized text-only script JSON; defaults to embedded data"
    )
    parser.add_argument("--human-character")
    parser.add_argument(
        "--human-lines", help="JSON mapping stage or stage:round to the simulated human speech"
    )
    parser.add_argument("--vote-target")
    args = parser.parse_args()
    logging.basicConfig(level=logging.ERROR)
    try:
        asyncio.run(run(args))
    except Exception as exc:
        import traceback

        traceback.print_exc()
        raise SystemExit(type(exc).__name__) from None
