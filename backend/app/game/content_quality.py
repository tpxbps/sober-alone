"""Versioned gameplay contract and canonical content, shared by authoring and upkeep."""

from __future__ import annotations

import hashlib
import json
from typing import Any

CAPABILITY_VERSION = "public-discussion-v2"
RUBRIC_VERSION = "script-quality-v3"
GAMEPLAY_CONTRACT = """【实际游戏能力｜public-discussion-v2】
本剧本用于一名真人与多个 AI 角色进行公开文字讨论。角色可阅读自己的剧本，系统按轮次向所有人
公开固定线索，最后投票并揭晓固定真相。@角色仍是公开发言。玩家不能实际私聊、移动搜证、
交换或销毁物品，也不能触发隐藏行动或平票重投。可选择单结局，或按最终单次投票的正确指认、
错误指认、平票、无有效票四种结果展示不同后续结局；案件真相不变，不依赖隐藏行动或AI临场判定。
历史剧情可以描述这些行为，但当前游玩任务
必须通过公开交流和推理完成。不要用“如果游戏允许”等措辞布置不存在的操作。
角色必须知道其本人经历和行为；不能为隐藏真相而对扮演者隐藏其已知的作案事实。
推理必需的证据应在投票前可获得，结局不能才补充决定性事实。
【文本受众与知情边界】以上能力约束用于编剧和AI执行，不得照抄进角色正文、速览、公开简介或线索。
个人剧本只写该角色的经历、关系、秘密、动机与疑问；用自然叙述表达所见和不确定，不写系统限制、
旧稿纠错清单、工具字段名或强制辩解话术。速览只从该角色个人稿提炼，不能由全知真相补充。
“你不知道某人其实是凶手/亲属”仍然泄露了秘密，应完全去掉该未知事实；AI角色输入同样遵守。
角色已经说过的谎可标明为既往对外说辞，但真实经历必须清楚；保留玩家自行判断和表达的空间。
故事中的必要设定可自然交代，不新增首次玩法教程，不以大量规则说明代替人物和推理体验。"""

DIMENSIONS = {
    "compatibility": ("系统匹配与任务可执行性", 10),
    "consistency": ("时间线、因果和真相一致性", 15),
    "deducibility": ("证据完整性与可推理性", 20),
    "fairness": ("角色公平性与辩解空间", 15),
    "interaction": ("交流空间与分轮节奏", 15),
    "narrative": ("叙事与人物塑造", 20),
    "onboarding": ("新手指引与表达清晰度", 5),
}


def _decode(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value) if value else default
    return value if value is not None else default


def _prose(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").strip()


def _process(items: list[dict]) -> list[dict]:
    return [
        {
            **{k: _prose(item[k]) for k in ("type", "stage_title", "system_notice") if k in item},
            **({"children": _process(item["children"])} if item.get("children") else {}),
        }
        for item in items
    ]


def script_content(script: dict, characters: list[dict] | None = None) -> dict:
    """Explicit allowlist: never hash credentials, ratings, timestamps or media URLs.

    Accept database rows, runtime script snapshots and normalized editor sections.
    Array order is meaningful for scenes and clues; characters are sorted by ID.
    """
    characters = (
        characters
        if characters is not None
        else script.get("character_data", script.get("characters", []))
    )
    result = {k: _prose(script.get(k)) for k in ("title", "overview", "description", "full_truth")}
    result.update({k: int(script.get(k) or 0) for k in ("difficulty", "player_count")})
    from app.game.endings import normalize_endings

    endings = normalize_endings(script.get("ending_config"))
    # Omit the default so upgrading does not invalidate legacy content or resources.
    if endings:
        result["ending_config"] = endings
    result["game_full_process"] = _process(
        _decode(script.get("game_flow", script.get("game_full_process")), [])
    )
    result["free_speech_limits"] = _decode(script.get("free_speech_limits"), [])
    result["clue_stages"] = [
        {
            "stage": stage.get("stage"),
            "overview": _prose(stage.get("overview")),
            "free_discussion_notice": _prose(stage.get("free_discussion_notice")),
            "items": [
                {k: _prose(item.get(k)) for k in ("id", "summary", "content")}
                for item in stage.get("items", [])
            ],
        }
        for stage in _decode(script.get("clue_stages"), [])
    ]
    result["characters"] = []
    for character in sorted(
        characters or [], key=lambda c: str(c.get("character_id", c.get("name")))
    ):
        item = {
            k: _prose(character.get(k))
            for k in (
                "character_id",
                "name",
                "gender",
                "occupation",
                "profile",
                "character_script",
                "system_prompt",
            )
        }
        item["age"] = character.get("age")
        item["character_script_summary"] = _prose(
            character.get("character_script_summary") or character.get("script_summary") or ""
        )
        result["characters"].append(item)
    return result


def content_fingerprint(script: dict, characters: list[dict] | None = None) -> str:
    serialized = json.dumps(script_content(script, characters), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def public_ai_review(review: dict | None, fingerprint: str) -> dict | None:
    """Only expose numeric, non-spoiling fields from a current, valid review."""
    if not review or not fingerprint or review.get("content_fingerprint") != fingerprint:
        return None
    if (
        review.get("capability_version") not in ("public-discussion-v1", CAPABILITY_VERSION)
        or review.get("rubric_version") != RUBRIC_VERSION
    ):
        return None
    score = review.get("score")
    dimensions = review.get("dimensions", {})
    if type(score) is not int or not 0 <= score <= 100:
        return None
    if set(dimensions) != set(DIMENSIONS) or any(
        type(value) not in (int, float) or not 0 <= value <= 5 for value in dimensions.values()
    ):
        return None
    return {
        "score": score,
        "model": str(review.get("model", "")),
        "reviewed_at": str(review.get("reviewed_at", "")),
        "rubric_version": RUBRIC_VERSION,
        "dimensions": [
            {"key": key, "label": label, "weight": weight, "score": dimensions[key]}
            for key, (label, weight) in DIMENSIONS.items()
        ],
    }
