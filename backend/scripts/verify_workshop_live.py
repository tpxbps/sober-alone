"""Opt-in, real-provider creation acceptance in an isolated local database.

Never run in CI. Pass an existing env file; credentials and generated artifacts
remain outside source control. Both modes use the configured real text model.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def prepare():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--resources", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    load_dotenv(args.env_file, override=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(root / 'app.db').as_posix()}"
    os.environ["CHROMA_PERSIST_DIR"] = str(root / "chroma")
    from app.core import config

    config.LOCAL_DATA_DIR = root
    if not args.resources:
        for key in ("ZHIPUAI_API_KEY", "DOUBAO_API_KEY", "MIMO_API_KEY"):
            setattr(config.settings, key, None)
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    return args, root


async def run(args, root):
    import httpx

    from app.core.config import settings
    from app.main import app

    logging.getLogger("httpx").setLevel(logging.WARNING)
    pointer = root / "acceptance.json"
    record = (
        json.loads(pointer.read_text(encoding="utf-8"))
        if pointer.exists()
        else {"author_key": str(uuid.uuid4()), "steps": []}
    )

    def save():
        pointer.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://workshop.test",
            headers={"X-Sober-Author-Key": record["author_key"]},
            timeout=600,
        ) as client,
    ):

        async def post(path, body):
            response = await client.post("/api/v1" + path, json=body)
            response.raise_for_status()
            return response.json()

        async def wait(accepted):
            operation_id = accepted["operation_id"]
            record["operation_id"] = operation_id
            save()
            last = ""
            while True:
                response = await client.get(
                    f"/api/v1/script-editor/{record['thread_id']}/operations/{operation_id}"
                )
                response.raise_for_status()
                value = response.json()
                stage = value.get("current_step", value.get("target_step", ""))
                if stage != last:
                    print(
                        json.dumps({"stage": stage, "status": value["operation_status"]}),
                        flush=True,
                    )
                    last = stage
                if value["operation_status"] == "failed":
                    record["failure"] = value.get("error_message", "failed")
                    save()
                    raise RuntimeError("Operation failed; inspect the private acceptance artifact")
                if value["operation_status"] in {"complete", "paused"}:
                    record.pop("operation_id", None)
                    record["steps"].append(
                        {"stage": value["current_step"], "checkpoint": value.get("checkpoint_id")}
                    )
                    (root / "latest-state.json").write_text(
                        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    save()
                    return value
                await asyncio.sleep(2)

        if not record.get("thread_id"):
            accepted = await post(
                "/script-editor/start",
                {
                    "player_count": 3,
                    "num_clue_rounds": 1,
                    "difficulty": 1,
                    "user_idea": "写一个简洁可游玩的旅馆悬疑短本，三个可扮演角色：许舟、陆宁、顾青；死者是馆主。暴雨告别宴后馆主死在书房，开局为次日清晨众人得知死亡但鉴定尚未公布。许舟昨晚为掩盖账目调换杯子，他知道自己的行为；陆宁曾独自到仓库拿旧账册，他人当时没有看见；顾青寄过匿名举报信。馆主和陆宁长期自愿互利合作，从来没有胁迫关系。馆主意外喝下许舟调换的杯中毒物而死，固定真相、无预谋主题。唯一一轮线索公布账本、杯底残留检验与门廊记录，使玩家可推出换杯行为，个人稿不能提前知道其他人到场或次日鉴定。请保持角色本各约400字、全文紧凑，不加支线。",
                },
            )
            record["thread_id"] = accepted["thread_id"]
            save()
            state = await wait(accepted)
        elif record.get("operation_id"):
            state = await wait({"operation_id": record["operation_id"]})
        else:
            state = (await client.get(f"/api/v1/script-editor/{record['thread_id']}/state")).json()
        for _ in range(20):
            step = state["current_step"]
            if state.get("is_complete"):
                break
            if args.retry_failed and state["state"].get("error_message"):
                accepted = await post(
                    f"/script-editor/{record['thread_id']}/resume",
                    {
                        "action": "retry_failed",
                        "request_id": str(uuid.uuid4()),
                        "expected_checkpoint_id": state.get("checkpoint_id"),
                    },
                )
                args.retry_failed = False
            elif step in {"outline_wait", "generate_outline"}:
                session = state["state"]["outline_session"]
                accepted = await post(
                    f"/script-editor/{record['thread_id']}/outline/actions",
                    {
                        "action": "stop_questions",
                        "request_id": str(uuid.uuid4()),
                        "expected_revision": session["revision"],
                    },
                )
            elif step in {
                "review_outline",
                "review_first_draft",
                "review_report",
                "review_final",
                "review_game_data",
            }:
                body = {
                    "action": "confirm",
                    "request_id": str(uuid.uuid4()),
                    "expected_checkpoint_id": state.get("checkpoint_id"),
                }
                if step == "review_game_data":
                    body["game_data_sections"] = state["state"]["game_data_sections"]
                else:
                    field = {
                        "review_outline": "outline",
                        "review_first_draft": "first_draft",
                        "review_report": "review_opinion",
                        "review_final": "final_draft",
                    }[step]
                    body["content"] = state["state"][field]
                accepted = await post(f"/script-editor/{record['thread_id']}/resume", body)
            else:
                raise RuntimeError(
                    f"Unfinished acceptance stage: {step}; inspect latest-state.json"
                )
            state = await wait(accepted)
            if state["state"].get("error_message"):
                raise RuntimeError("Workflow reported a failure; inspect latest-state.json")
        if not state.get("is_complete"):
            raise RuntimeError("Workflow did not complete")
        script = state["state"]
        game = await post(
            "/game/create",
            {
                "script_id": script["script_id"],
                "human_character_id": script["characters"][0]["character_id"],
            },
        )
        if not game.get("success"):
            raise RuntimeError("Generated script could not start a game")
        game_state = await client.get(f"/api/v1/game/{game['session_id']}/state")
        game_state.raise_for_status()
        record.update(
            completed=True,
            model=settings.SCRIPT_EDITOR_MODEL,
            resources=args.resources,
            script_id=script["script_id"],
            game_session_id=game["session_id"],
            game_state_verified=True,
        )
        record.pop("failure", None)
        save()
        print(
            json.dumps({"completed": True, "resources": args.resources, "game_started": True}),
            flush=True,
        )


if __name__ == "__main__":
    arguments, artifacts = prepare()
    asyncio.run(run(arguments, artifacts))
