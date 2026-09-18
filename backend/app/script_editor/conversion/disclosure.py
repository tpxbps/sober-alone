"""Evidence-bound disclosure plan. Writers only receive material for their audience."""

import asyncio
import hashlib
import json
import logging
import re
import unicodedata
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.script_editor.conversion.contracts import CharacterBrief


class Fact(BaseModel):
    id: str = ""
    source_id: int | None = Field(
        default=None, description="引用原文片段的编号；优先通过编号引用而非抄写"
    )
    quote: str = Field(
        default="", description="终稿中逐字连续原文；事实粒度最小化，不能把他人秘密合并进同一条"
    )
    known_by: list[str] = Field(
        default_factory=list, description="游戏开局已知这条完整事实的角色姓名"
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
    r"|(?:不得|不应|不能|不可|不该)(?:提前|事先|在开局时)?(?:知道|知晓|获知|得知)"
)


def contains_unknown_evidence(quote: str) -> bool:
    for match in UNKNOWN_EVIDENCE.finditer(quote):
        tail = quote[match.end() :].lstrip(" ：:，,、")
        # An unresolved question discloses no answer: "不知道谁才是真凶".
        if re.match(r"(?:究竟|到底)?(?:是)?(?:谁|什么|怎么|为何|为什么|是否|有无|哪)", tail):
            continue
        return True
    return False


def validate_no_secret_inventory(text: str, role: str, names: list[str]) -> None:
    for sentence in re.split(r"[。！？\n]", text):
        if not contains_unknown_evidence(sentence):
            continue
        if any(name != role and name in sentence for name in names) and re.search(
            r"到过|到达|来过|来到|离开|开(?:过)?窗|放入|投毒|下药|换过|拿走|带走|杀死|行凶|真凶",
            sentence,
        ):
            raise ValueError(
                "个人内容不能以否定句列举他人秘密行动。删除这类列举，不得改成已知事实；"
                f"保留本人实际行为。需修订的句子：{sentence}"
            )


def source_excerpt(quote: str, source: str) -> str | None:
    """Restore source formatting only; never accept a paraphrase as evidence."""
    if quote in source:
        return quote

    def indexed(text):
        chars, positions = [], []
        for i, char in enumerate(text):
            if char.isspace() or char in "*`#":
                continue
            normalized = unicodedata.normalize("NFKC", char)
            chars.extend(normalized)
            positions.extend([i] * len(normalized))
        return "".join(chars), positions

    needle, _ = indexed(quote)
    haystack, positions = indexed(source)
    start = haystack.find(needle) if needle else -1
    if start < 0:
        return None
    return source[positions[start] : positions[start + len(needle) - 1] + 1]


async def invoke(base_llm, schema, system: str, material, *, validate=None):
    from app.script_editor.llm import invoke_structured

    return await invoke_structured(base_llm, schema, system, material, validate=validate)


def validate_plan(
    plan: DisclosurePlan,
    source: str,
    count: int,
    rounds: int,
    *,
    require_role_material: bool = True,
) -> None:
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
                f"{fact.id}: 不知情陈述会泄露未知事实，known_by须为空且不能public；"
                "若同句有本人行为，只截取该行为的连续原文quote，不带未知的宾语"
            )
        unknown = set(fact.known_by) - names
        if unknown:
            errors.append(
                f"{fact.id}: 知情角色引用不存在 {sorted(unknown)}；仅填可扮演名单中的姓名，不能填NPC或死者"
            )
        if not fact.before_start and (fact.known_by or fact.release == "public"):
            errors.append(f"{fact.id}: 开局后事实known_by须为空，不能release=public")
        if fact.release == "round" and (fact.round is None or not 1 <= fact.round <= rounds):
            errors.append(f"{fact.id}: 线索轮次须在1至{rounds}之间")
    if require_role_material and any(
        not any(c.name in f.known_by for f in plan.facts) for c in plan.characters
    ):
        errors.append("角色缺少有来源的亲历材料")
    if errors:
        raise ValueError("；".join(errors))


class CastAndStart(BaseModel):
    characters: list[CharacterBrief]
    game_start: str = Field(description="玩家开始扮演的时点，明确哪些调查尚未发生")
    start_source_id: int = Field(description="支持开局时点的原文片段编号，必须取自输入编号")


class FactBatch(BaseModel):
    facts: list[Fact] = Field(default_factory=list)


DISCLOSURE_VERSION = "disclosure-batches-v5"


def source_batches(source: str) -> tuple[dict[int, str], list[list[int]]]:
    pieces = []
    for part in re.split(r"(?<=[。！？\n])", source):
        part = part.strip()
        # Bound even a source that contains no sentence punctuation.
        pieces.extend(part[i : i + 600] for i in range(0, len(part), 600))
    sources = dict(enumerate(pieces, 1))
    batches, current, size = [], [], 0
    for key, value in sources.items():
        if current and (len(current) == 24 or size + len(value) > 3000):
            batches.append(current)
            current, size = [], 0
        current.append(key)
        size += len(value)
    if current:
        batches.append(current)
    return sources, batches


async def extract_plan(base_llm, state: dict) -> dict:
    from app.script_editor.conversion.progress import (
        _update_convert_task,
        add_disclosure_task,
    )
    from app.script_editor.llm import StructuredOutputTruncated
    from app.script_editor.outline.runtime import current_runtime

    base_llm = base_llm.model_copy(update={"max_tokens": 8192})
    source = state.get("final_draft", "")
    refinement = state.get("refinement") or {}
    feedback = ""
    if refinement.get("target") == "review_game_data":
        source += "\n作者当前编辑的游戏数据：\n" + json.dumps(
            state.get("game_data_sections", {}), ensure_ascii=False
        )
        feedback = refinement.get("feedback", "")
    sources, batches = source_batches(source)
    if not sources:
        raise ValueError("终稿为空，无法整理事实")
    count, rounds = state.get("player_count", 4), state.get("num_clue_rounds", 2)
    fingerprint = hashlib.sha256(
        json.dumps(
            [source, count, rounds, feedback, DISCLOSURE_VERSION],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    runtime = current_runtime.get()
    candidates = [state.get("disclosure_cache") or {}, runtime.disclosure_cache if runtime else {}]
    previous = next((c for c in reversed(candidates) if c.get("fingerprint") == fingerprint), {})
    cache = {
        "fingerprint": fingerprint,
        "batches": dict(previous.get("batches", {})),
        "cast": previous.get("cast"),
        "coverage_feedback": previous.get("coverage_feedback", ""),
    }
    state["disclosure_cache"] = cache
    script_id = state.get("script_id", "")

    async def persist():
        if runtime:
            runtime.disclosure_cache = cache
            runtime.queue_progress("disclosure_cache", json.loads(json.dumps(cache)))
            await runtime.drain_progress()

    def validate_cast(cast):
        names = [c.name for c in cast.characters]
        if len(names) != count or len(set(names)) != count:
            raise ValueError(f"characters 必须包含恰好 {count} 个不同的可扮演角色，排除死者和NPC")
        piece = sources.get(cast.start_source_id, "")
        if not piece:
            raise ValueError(f"start_source_id={cast.start_source_id} 不存在，必须取自输入片段编号")

    if cache.get("cast"):
        cast = CastAndStart.model_validate(cache["cast"])
        validate_cast(cast)
    else:
        cast = await invoke(
            base_llm,
            CastAndStart,
            "仅从最新终稿识别可扮演角色及玩家开始扮演的时点，不提取全部事实，不续写。"
            "角色职业仅写公开身份。引用支持开局时点的start_source_id，明确调查尚未发生的部分。",
            {"原文片段": sources, "人数": count, "改进要求": feedback},
            validate=validate_cast,
        )
        cache["cast"] = cast.model_dump()
        await persist()
    _update_convert_task(script_id, "discover_chars", "complete")
    cast_material = {**cast.model_dump(), "start_evidence": sources[cast.start_source_id]}
    semaphore = asyncio.Semaphore(2)
    system = (
        "你从终稿提取原子事实与披露范围，不续写。全稿仅用于判断跨段关系；只提取本批片段的事实。"
        "每条source_id必须属于本批；通常quote留空由程序填回，混合知情范围时只引用更小的连续原文。"
        "跳过修辞、标题及重复信息，不能遗漏本人行为、动机、关系、证据。"
        "known_by是开局已知完整事实的可扮演角色姓名，排除NPC。本人亲历的行为、对话须保留并归本人知情。"
        "对话双方知道对话发生及其原话，不代表知道话中指控的真伪。开局后的鉴定、发现known_by为空，不能public。"
        "同句先后出现两人的独立行为不代表双方互知。比如‘乙到门口时甲已离开’，拆出甲离开与乙到场，各归本人，不让甲知道乙后来到场。"
        "‘不得提前知道’‘本不可获知’属于编剧的信息边界说明，不是角色已知事实；跳过这类元说明，仅保留可独立引用的本人行为。"
        "public只限开局全员已经知道的身份、环境与共同经历；必须明确known_by为全部角色。没有知情依据时默认不公开，不能因为故事背景或关系介绍就认定全员知情。"
        "私人资金比例、别人的心理和动机、单独会面不因写在终稿中就公开。共同宴席中某人内心的反应，也只能归本人知情。"
        "严格遵守game_start描述的尚未发现内容：物证虽然已经存在，未被发现前不能归入开局公开；线索后续公布与物理发生是不同时间。"
        "指定轮次证据release=round，真相解释release=reveal。同一事实在不同章节重复，始终沿用最严格的信息边界，不因出现在关系总览或开篇就扩大范围。"
        "知情不能仅因事实提及某人而推断。‘不知道别人来过’仍泄露别人到场，不能整句进入个人材料；"
        "同句本人行动需单独截取原文保留。禁止编造固定疑问。只返回当前批次facts，不重复角色名单。"
    )

    async def extract(ids):
        key = f"{ids[0]}-{ids[-1]}"
        task_id = f"facts_{key}"
        add_disclosure_task(script_id, task_id, f"整理事实与披露范围（片段 {key}）")

        def validate_batch(batch):
            names = {c.name for c in cast.characters}
            for fact in batch.facts:
                if fact.source_id not in ids:
                    raise ValueError(f"source_id={fact.source_id} 不属于本批片段 {key}")
                piece = sources[fact.source_id]
                excerpt = source_excerpt(fact.quote, piece) if fact.quote else piece
                if excerpt is None:
                    raise ValueError(
                        f"片段{fact.source_id}的quote必须为连续原文，不能改写：{piece}"
                    )
                fact.quote = excerpt
                # These fields describe playable-role knowledge, never NPC memory.
                fact.known_by = [name for name in fact.known_by if name in names]
                if fact.release == "public" and set(fact.known_by) != names:
                    # Explicit restricted knowledge always wins over a public label.
                    fact.release = "reveal"
                if not fact.before_start:
                    fact.known_by = []
                    if fact.release == "public":
                        fact.release = "reveal"
                        fact.round = None
                if fact.release == "round":
                    # The author selected the number of rounds. Missing or out-of-range
                    # model labels map to the last available round, never past voting.
                    fact.round = max(1, min(fact.round or rounds, rounds))
                else:
                    fact.round = None
                fact.id = (
                    f"s{fact.source_id}-" + hashlib.sha256(fact.quote.encode()).hexdigest()[:12]
                )
            if batch.facts:
                validate_plan(
                    DisclosurePlan(**cast_material, facts=batch.facts),
                    source,
                    count,
                    rounds,
                    require_role_material=False,
                )

        if key in cache["batches"]:
            batch = FactBatch.model_validate(cache["batches"][key])
            validate_batch(batch)
            _update_convert_task(script_id, task_id, "complete")
            return batch.facts
        _update_convert_task(script_id, task_id, "running")
        try:
            async with semaphore:
                batch = await invoke(
                    base_llm,
                    FactBatch,
                    system,
                    {
                        "全稿": source,
                        "本批片段": {i: sources[i] for i in ids},
                        "角色与开局": cast_material,
                        "线索轮次": rounds,
                        "作者改进意见": feedback,
                        "需修复的遗漏": cache["coverage_feedback"],
                    },
                    validate=validate_batch,
                )
            cache["batches"][key] = batch.model_dump()
            await persist()
            _update_convert_task(script_id, task_id, "complete")
            return batch.facts
        except StructuredOutputTruncated:
            if len(ids) == 1:
                _update_convert_task(script_id, task_id, "failed")
                raise
            middle = len(ids) // 2
            children = await asyncio.gather(
                extract(ids[:middle]), extract(ids[middle:]), return_exceptions=True
            )
            for child in children:
                if isinstance(child, BaseException):
                    _update_convert_task(script_id, task_id, "failed")
                    raise child
            left, right = children
            cache["batches"][key] = FactBatch(facts=left + right).model_dump()
            await persist()
            _update_convert_task(script_id, task_id, "complete")
            return left + right
        except Exception:
            _update_convert_task(script_id, task_id, "failed")
            raise

    # Finish successful siblings before returning failure, so retries reuse them.
    results = await asyncio.gather(*(extract(ids) for ids in batches), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    facts = [fact for result in results for fact in result]
    missing = [c.name for c in cast.characters if not any(c.name in f.known_by for f in facts)]
    if missing:
        # An incomplete aggregate must not be cached as an unrepairable success.
        cache["coverage_feedback"] = (
            f"上次遗漏 {', '.join(missing)} 的亲历材料，请按原文补全，不可编造知情。"
        )
        affected = {i for i, piece in sources.items() if any(name in piece for name in missing)}
        for key in list(cache["batches"]):
            start, end = map(int, key.split("-"))
            if not affected or any(start <= i <= end for i in affected):
                del cache["batches"][key]
        await persist()
        raise ValueError(cache["coverage_feedback"])
    plan = DisclosurePlan(**cast_material, facts=facts)
    validate_plan(plan, source, count, rounds)
    result = plan.model_dump()
    old = {c["name"]: c.get("character_id") for c in state.get("characters", [])}
    for role in result["characters"]:
        role["character_id"] = old.get(role["name"]) or str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"{script_id}:{role['name']}")
        )
    return result


def audience_material(state: dict, *, role: str | None = None, scope: str = "public") -> dict:
    plan = state.get("disclosure_plan") or {}
    if not plan:
        raise ValueError("缺少可验证的披露安排，不能使用全知稿生成个人内容")
    names = {c["name"] for c in plan["characters"]}
    facts = [
        f
        for f in plan["facts"]
        if (
            (scope == "truth" or not contains_unknown_evidence(f["quote"]))
            and (
                (f["release"] == "public" and f["before_start"] and names.issubset(f["known_by"]))
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
    profile: str = Field(min_length=1)
    appearance: str = Field(min_length=1)
    tts_voice_id: str = ""
    step_voice_id: str = ""


class PublicScenes(BaseModel):
    opening_notice: str = Field(min_length=1)
    summary_notice: str = Field(min_length=1)
    vote_notice: str = Field(min_length=1)


class TruthScenes(BaseModel):
    truth_reveal_notice: str = Field(min_length=1)
    full_truth: str = Field(min_length=1)
