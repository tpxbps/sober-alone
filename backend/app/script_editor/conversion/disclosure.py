"""Evidence-bound disclosure plan. Writers only receive material for their audience."""

import asyncio
import json
import logging
import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.script_editor.conversion.contracts import CharacterBrief


class Fact(BaseModel):
    id: str
    source_id: int | None = Field(
        default=None, description="引用原文片段的编号；优先通过编号引用而非抄写"
    )
    quote: str = Field(
        default="", description="终稿中逐字连续原文；事实粒度最小化，不能把他人秘密合并进同一条"
    )
    known_by: list[str] = Field(
        default_factory=list, description="游戏开局已知这条完整事实的角色姓名"
    )
    actors: list[str] = Field(
        default_factory=list, description="这条事实中亲自行动且知道自己行为的角色姓名"
    )
    before_start: bool = Field(description="该事实及其中的鉴定、发现是否在游戏开局前已经发生")
    release: Literal["public", "round", "reveal"]
    round: int | None = None


class DisclosurePlan(BaseModel):
    characters: list[CharacterBrief]
    game_start: str = Field(description="玩家开始扮演的时点，明确哪些调查尚未发生")
    start_source_id: int | None = Field(default=None, description="确定游戏开局时点的原文片段编号")
    start_evidence: str = Field(default="", description="仅在未提供片段编号时填写连续逐字原文")
    facts: list[Fact] = Field(min_length=1)


logger = logging.getLogger(__name__)

# An ignorance statement can still disclose its object ("does not know the cup is poisoned").
# Keep such evidence for the planner/truth only, never in a writer's personal/public context.
UNKNOWN_EVIDENCE = re.compile(
    r"不(?:知道|知晓|知情|清楚|了解)|未(?:知晓|察觉|意识到)|没(?:有)?(?:察觉|意识到)|毫不知情"
)


def contains_unknown_evidence(quote: str) -> bool:
    return bool(UNKNOWN_EVIDENCE.search(quote))


async def invoke(base_llm, schema, system: str, material):
    result = await asyncio.wait_for(
        base_llm.with_structured_output(
            schema,
            method="function_calling",
            include_raw=True,
            tool_choice=schema.__name__,
        ).ainvoke(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": material
                    if isinstance(material, str)
                    else json.dumps(material, ensure_ascii=False),
                },
            ]
        ),
        timeout=240,
    )
    if isinstance(result, dict) and "raw" in result:
        from app.script_editor.services.execution import observe_model

        observe_model(result["raw"])
        parsed = result.get("parsed")
        if parsed is None:
            raw = result["raw"]
            logger.warning(
                "Structured %s returned no object: finish=%s tools=%s chars=%s",
                schema.__name__,
                raw.response_metadata.get("finish_reason"),
                [t.get("name") for t in raw.tool_calls],
                len(str(raw.content)),
            )
            if result.get("parsing_error"):
                raise ValueError("结构化返回格式不完整，请重新输出完整对象") from result[
                    "parsing_error"
                ]
            raise ValueError("模型未返回所要求的结构化对象，请调用指定函数而非输出正文")
        result = parsed
    return schema.model_validate(result)


def validate_plan(plan: DisclosurePlan, source: str, count: int, rounds: int) -> None:
    names = {c.name for c in plan.characters}
    errors = []
    if len(names) != count or len(plan.characters) != count:
        errors.append("终稿中的可扮演角色数量不匹配")
    if not plan.start_evidence or plan.start_evidence not in source:
        errors.append("游戏开始时点缺少原文依据")
    ids = set()
    for fact in plan.facts:
        if fact.id in ids or not fact.quote or fact.quote not in source:
            errors.append(f"{fact.id}: source_id必须指向现有原文片段，事实编号不能重复")
        ids.add(fact.id)
        if contains_unknown_evidence(fact.quote) and (fact.known_by or fact.release == "public"):
            errors.append(
                f"{fact.id}: 不知情陈述会泄露未知事实，known_by和actors须为空且不能public；"
                "若同句有本人行为，只截取该行为的连续原文quote，不带未知的宾语"
            )
        unknown = set(fact.known_by + fact.actors) - names
        if unknown:
            errors.append(
                f"{fact.id}: 知情角色引用不存在 {sorted(unknown)}；仅填可扮演名单中的姓名，不能填NPC或死者"
            )
        missing = set(fact.actors) - set(fact.known_by)
        if fact.before_start and missing:
            errors.append(
                f"{fact.id}: 遗漏本人实际行为，开局前actors {sorted(missing)} 必须在known_by中"
            )
        if not fact.before_start and (fact.known_by or fact.release == "public"):
            errors.append(f"{fact.id}: 开局后事实known_by须为空，不能release=public")
        if fact.release == "round" and (fact.round is None or not 1 <= fact.round <= rounds):
            errors.append(f"{fact.id}: 线索轮次须在1至{rounds}之间")
    if any(not any(c.name in f.known_by for f in plan.facts) for c in plan.characters):
        errors.append("角色缺少有来源的亲历材料")
    if errors:
        raise ValueError("；".join(errors))


async def extract_plan(base_llm, state: dict) -> dict:
    # Disclosure tables are larger than prose answers; provider defaults can truncate
    # a tool call before a parseable object is emitted. Keep an explicit bounded budget.
    base_llm = base_llm.model_copy(update={"max_tokens": 16384})
    source = state.get("final_draft", "")
    # Manual game-data edits are the revision baseline. They are planner-only inputs;
    # they can never be appended wholesale to an individual character's context.
    # A manually confirmed final draft supersedes earlier outline constraints.
    # Do not reintroduce stale canon here, and never send it to role writers.
    refinement = (
        (state.get("refinement") or {}).get("feedback", "")
        if (state.get("refinement") or {}).get("target") == "review_game_data"
        else ""
    )
    if (state.get("refinement") or {}).get("target") == "review_game_data":
        source += "\n\n作者当前编辑的游戏数据：\n" + json.dumps(
            state.get("game_data_sections", {}), ensure_ascii=False
        )
    system = (
        "从作者确认的最新终稿提取事实与披露安排，不续写。提取恰好指定人数的可扮演角色，排除死者/NPC。"
        "职业等角色基本信息仅写公开身份，秘密身份必须进入有知情范围的事实。仅提取剧情相关事实，跳过氛围修辞和重复段落。"
        "先确定游戏开局时点，引用start_source_id。逐条提取最小完整事实，source_id填写原文片段编号，quote通常留空由程序填回；若片段混合不同知情范围，quote填写该片段中更小的连续原文。不要改写引文；不要把不同知情范围合成一条。"
        "完整覆盖本人行为、动机、关系与证据，尤其保留行为人自己知道的作案事实。"
        "known_by和actors仅限characters中的可扮演角色姓名，排除NPC、死者；known_by表示该事实在开局已被哪些人知道；公开身份背景release=public，系统线索按指定轮次round，真相解释reveal。"
        "后续公开的鉴定不进入开局记忆。known_by不能仅因事实提及某角色就填写该角色。真相总结中判定其无罪、与毒酒无关等，是全知结论，不是角色已经获知毒物存在的依据。"
        "同一片段只要含有该角色不可知的细节，整条都不能分给他；改用其他只包含其亲历的来源。角色自己可能怀疑死因，但未见检验时不能确知。"
        "某人不知道他人到场，绝不能将那条到场事实分给该角色，否定句仍泄密。"
        "不新增证据或固定疑问。作者改进意见与当前编辑稿优先，保留未要求修改的事实。"
    )
    pieces = [part.strip() for part in re.split(r"(?<=[。！？\n])", source) if part.strip()]
    sources = {i + 1: part for i, part in enumerate(pieces)}
    material = {
        "原文片段": sources,
        "人数": state.get("player_count", 4),
        "轮次": state.get("num_clue_rounds", 2),
        "改进要求": refinement,
    }
    # Repair the actual validation failure, within one bounded extraction task.
    # Never bypass disclosure validation or silently fall back to the full draft.
    for attempt in range(3):
        try:
            plan = await invoke(base_llm, DisclosurePlan, system, material)
            if plan.start_source_id is not None:
                plan.start_evidence = sources.get(plan.start_source_id, "")
            for fact in plan.facts:
                if fact.source_id is not None:
                    piece = sources.get(fact.source_id, "")
                    if fact.quote and fact.quote not in piece:
                        raise ValueError(f"{fact.id}: quote必须是source_id所指片段的连续原文")
                    fact.quote = fact.quote or piece
            validate_plan(
                plan, source, state.get("player_count", 4), state.get("num_clue_rounds", 2)
            )
            break
        except ValueError as error:
            logger.warning("Disclosure validation attempt %s: %s", attempt + 1, error)
            if attempt == 2:
                raise
            material = {
                **material,
                "上次提取": plan.model_dump() if "plan" in locals() else None,
                "必须修复的校验问题": str(error),
            }
    result = plan.model_dump()
    old = {c["name"]: c.get("character_id") for c in state.get("characters", [])}
    for role in result["characters"]:
        role["character_id"] = old.get(role["name"]) or str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{state.get('script_id', '')}:{role['name']}")
        )
    return result


def audience_material(state: dict, *, role: str | None = None, scope: str = "public") -> dict:
    plan = state.get("disclosure_plan") or {}
    if not plan:
        raise ValueError("缺少可验证的披露安排，不能使用全知稿生成个人内容")
    facts = [
        f
        for f in plan["facts"]
        if (
            (scope == "truth" or not contains_unknown_evidence(f["quote"]))
            and (
                f["release"] == "public"
                or (role and role in f["known_by"] and f["before_start"])
                or (scope == "clues" and f["release"] == "round")
                or scope == "truth"
            )
        )
    ]
    # Crucially omit other roles' knowledge, secret IDs and the rest of the plan.
    return {
        "材料": [
            {"原文": f["quote"], **({"公布轮次": f["round"]} if scope == "clues" else {})}
            for f in facts
        ]
    }


class PersonalScript(BaseModel):
    character_script: str = Field(min_length=1)


class RoleReading(BaseModel):
    script_summary: str = Field(
        min_length=1,
        max_length=380,
        description="角色速览，150至300字，最多380字符；保留本人关键行为，不复述全文",
    )
    system_prompt: str = Field(min_length=1)


class PublicCharacter(BaseModel):
    profile: str
    appearance: str
    tts_voice_id: str = ""
    step_voice_id: str = ""


class PublicScenes(BaseModel):
    opening_notice: str
    summary_notice: str
    vote_notice: str


class TruthScenes(BaseModel):
    truth_reveal_notice: str
    full_truth: str
