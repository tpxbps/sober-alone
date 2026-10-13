"""Conversion orchestration behind the LangGraph node facade."""

import asyncio
import json
import logging
import uuid
from typing import Any

from app.core.config import settings
from app.core.inference import gather_inference, raise_for_inference_recovery
from app.game.clues import derive_game_process, normalize_clue_stages, render_clue_markdown
from app.script_editor.conversion.cache import ConversionCache, cached_output
from app.script_editor.conversion.contracts import (
    ClueStagesResult,
    ScenesResult,
    ScriptMetadata,
    SingleCharacterResult,
)
from app.script_editor.conversion.disclosure import (
    PersonalScript,
    PublicScenes,
    RoleReading,
    TruthScenes,
    audience_material,
    extract_plan,
    invoke,
    validate_no_secret_inventory,
)
from app.script_editor.conversion.progress import (
    _add_character_tasks,
    _init_convert_progress,
    _mark_convert_complete,
    _publish_convert_progress,
    _update_convert_task,
    get_convert_progress,
    task_failure_reason,
)
from app.script_editor.conversion.prompts import (
    CHARACTER_SYSTEM,
    CLUES_SYSTEM,
    METADATA_SYSTEM,
    SCENES_SYSTEM,
)
from app.script_editor.conversion.public_material import public_bundle, public_character
from app.script_editor.state import STEP_CONVERT, ScriptGenState

logger = logging.getLogger(__name__)


def character_task_id(char):
    return f"char_{char.get('character_id') or char['name']}"


def _character_prompt(name: str) -> str:
    prompt = CHARACTER_SYSTEM.format(char_name=name)
    if settings.INFERENCE_BACKEND == "tokendance":
        from app.services.voices import MINIMAX_VOICES

        prompt = prompt.split("### step_voice_id")[0]
        prompt += "\n### tts_voice_id\n结合性别、年龄、职业与性格，从以下音色选择一项：\n"
        prompt += "\n".join(f"{i}: {label}（{gender}）" for i, label, gender in MINIMAX_VOICES)
    return prompt


def _get_structured_llm():
    from app.script_editor.llm import create_editor_llm as create_llm

    return create_llm(
        model=settings.SCRIPT_EDITOR_MODEL or "deepseek-flash",
        temperature=0.5,
        timeout=180,
        max_retries=0,
        disable_thinking=True,
    )


def _build_characters_summary(characters: list[dict]) -> str:
    parts = []
    for c in characters:
        parts.append(
            f"- {c.get('name', '?')}: {c.get('gender', '?')}, "
            f"{c.get('age', '?')}岁, {c.get('occupation', '?')}"
        )
    return "\n".join(parts)


def _assign_mimo_voice(gender: str) -> str:
    """Assign mimo-v2.5-tts voice for static audio generation."""
    g = (gender or "").strip()
    return "茉莉" if g in ("女", "女性", "female") else "苏打"


# step-tts-mini 可用音色（用于游戏中实时 TTS）
STEP_MALE_VOICES = [
    "wenrounansheng",
    "wenrougongzi",
    "yuanqinansheng",
    "cixingnansheng",
    "zhengpaiqingnian",
    "qingniandaxuesheng",
    "boyinnansheng",
    "ruyananshi",
    "shenchennanyin",
]
STEP_FEMALE_VOICES = [
    "elegantgentle-female",
    "livelybreezy-female",
    "jingdiannvsheng",
    "wenroushunv",
    "tianmeinvsheng",
    "qingchunshaonv",
    "yuanqishaonv",
    "linjiajiejie",
    "qinqienvsheng",
    "wenrounvsheng",
    "jilingshaonv",
    "ruanmengnvsheng",
    "youyanvsheng",
    "lengyanyujie",
    "shuangkuaijiejie",
    "wenjingxuejie",
    "linjiameimei",
    "zhixingjiejie",
]
ALL_STEP_VOICES = set(STEP_MALE_VOICES + STEP_FEMALE_VOICES)


def _fallback_step_voice(gender: str) -> str:
    """Fallback step-tts-mini voice_id when LLM doesn't provide one."""
    g = (gender or "").strip()
    return "cixingnansheng" if g not in ("女", "女性", "female") else "wenroushunv"


def _validate_step_voice(voice_id: str, gender: str) -> str:
    """Validate LLM-returned step_voice_id; fallback if invalid."""
    if settings.INFERENCE_BACKEND == "tokendance":
        from app.services.voices import resolve_minimax_voice

        return resolve_minimax_voice(voice_id, {"gender": gender})
    if voice_id and voice_id in ALL_STEP_VOICES:
        # Cross-check: male voices for male chars, female voices for female chars
        g = (gender or "").strip()
        is_female = g in ("女", "女性", "female")
        if is_female and voice_id in STEP_FEMALE_VOICES:
            return voice_id
        if not is_female and voice_id in STEP_MALE_VOICES:
            return voice_id
        # Gender mismatch but valid voice — still accept it
        return voice_id
    return _fallback_step_voice(gender)


def _clamp_free_speech_limits(limits: list[int], num_rounds: int) -> list[int]:
    """确保 free_speech_limits 长度为 num_rounds，值为 1-3"""
    if not limits:
        return [2] * num_rounds
    clamped = [max(1, min(3, v)) for v in limits[:num_rounds]]
    while len(clamped) < num_rounds:
        clamped.append(2)
    return clamped


# === 并行 LLM 调用封装 ===


async def _run_game_clues(base_llm, script_id: str, state: ScriptGenState, chars_summary: str):
    """并行任务：生成线索阶段数据"""
    _update_convert_task(script_id, "game_flow", "running")
    num_rounds = state.get("num_clue_rounds", 2)
    try:
        user_msg = (
            f"## 剧本标题\n{state.get('script_title', '')}\n\n"
            f"## 角色列表（{state.get('player_count', 4)}人）\n{chars_summary}\n\n"
            f"## 按轮次披露的材料\n{json.dumps(audience_material(state, scope='clues'), ensure_ascii=False)}\n"
            f"请设计恰好 {num_rounds} 轮线索发现阶段。"
        )

        def validate_clues(value):
            if len(value.clue_stages) != num_rounds:
                raise ValueError(f"clue_stages 必须包含恰好 {num_rounds} 轮")
            if any(
                not stage.items
                or any(not item.content.strip() or not item.summary.strip() for item in stage.items)
                for stage in value.clue_stages
            ):
                raise ValueError("每轮必须包含有完整content与summary的items")

        result = await invoke(
            base_llm,
            ClueStagesResult,
            CLUES_SYSTEM.format(num_rounds=num_rounds),
            user_msg,
            validate=validate_clues,
        )
        if result:
            _update_convert_task(script_id, "game_flow", "complete")
            return result
        else:
            logger.error("game_clues: LLM returned None")
            _update_convert_task(script_id, "game_flow", "failed")
            return None
    except Exception as e:
        raise_for_inference_recovery(e)
        logger.error(f"game_clues failed: {e}", exc_info=True)
        _update_convert_task(script_id, "game_flow", "failed", task_failure_reason(e))
        return None


async def _run_game_scenes(base_llm, script_id: str, state: ScriptGenState, chars_summary: str):
    """并行任务：生成开场/投票/真相等非线索场景"""
    _update_convert_task(script_id, "game_scenes", "running")
    try:
        public, truth = await gather_inference(
            public_bundle(base_llm, state),
            cached_output(
                state,
                "truth",
                TruthScenes,
                state.get("final_draft", ""),
                lambda: invoke(
                    base_llm,
                    TruthScenes,
                    SCENES_SYSTEM + "\n本次只写真相和揭晓。",
                    {
                        "终稿": state.get("final_draft", ""),
                        "已确认事实": audience_material(state, scope="truth"),
                    },
                ),
            ),
        )
        result = ScenesResult(
            **public.model_dump(include=set(PublicScenes.model_fields)), **truth.model_dump()
        )
        if result:
            _update_convert_task(script_id, "game_scenes", "complete")
            return result
        else:
            logger.error("game_scenes: LLM returned None")
            _update_convert_task(script_id, "game_scenes", "failed")
            return None
    except Exception as e:
        raise_for_inference_recovery(e)
        logger.error(f"game_scenes failed: {e}", exc_info=True)
        _update_convert_task(script_id, "game_scenes", "failed", task_failure_reason(e))
        return None


def _merge_game_process(
    clues_result: ClueStagesResult | None,
    scenes_result: ScenesResult | None,
    num_rounds: int,
    script_title: str,
    outline: str,
    script_id: str,
) -> tuple[list[dict[str, Any]], list[int], str, str, list[dict[str, Any]]]:
    """
    将线索和场景结果按固定模板拼接为完整的 game_full_process。
    返回 (game_full_process, free_speech_limits, full_truth, truth_reveal_notice, clue_stages)
    """
    # 开场
    if scenes_result is None or not scenes_result.opening_notice.strip():
        raise ValueError("场景转换未完成")
    if clues_result is None or len(clues_result.clue_stages) != num_rounds:
        raise ValueError("线索转换未完成")
    opening_notice = scenes_result.opening_notice

    process: list[dict[str, Any]] = [
        {
            "type": "initial",
            "stage_title": "自我介绍阶段",
            "system_notice": opening_notice,
        },
    ]

    raw_clue_stages: list[dict[str, Any]] = []
    if clues_result:
        for index, stage_data in enumerate(clues_result.clue_stages[:num_rounds], start=1):
            raw_clue_stages.append(
                {
                    "stage": index,
                    "overview": stage_data.overview,
                    "items": [item.model_dump() for item in stage_data.items],
                    "free_discussion_notice": stage_data.free_discussion_notice,
                }
            )
    canonical_clue_stages = normalize_clue_stages(raw_clue_stages, script_id=script_id)

    # 线索轮次
    free_speech_limits = [2] * num_rounds
    if clues_result:
        if clues_result.free_speech_limits:
            free_speech_limits = _clamp_free_speech_limits(
                clues_result.free_speech_limits, num_rounds
            )
        for i in range(num_rounds):
            stage_data = canonical_clue_stages[i]
            clue_notice = render_clue_markdown(stage_data)
            discuss_notice = stage_data.get("free_discussion_notice", "")
            process.append(
                {
                    "type": "advancement",
                    "children": [
                        {
                            "stage_title": f"第{i + 1}轮-线索分析阶段",
                            "system_notice": clue_notice,
                        },
                        {
                            "stage_title": f"第{i + 1}轮-自由讨论阶段",
                            "system_notice": discuss_notice,
                        },
                    ],
                }
            )
    else:
        for i in range(num_rounds):
            process.append(
                {
                    "type": "advancement",
                    "children": [
                        {
                            "stage_title": f"第{i + 1}轮-线索分析阶段",
                            "system_notice": render_clue_markdown(canonical_clue_stages[i]),
                        },
                        {
                            "stage_title": f"第{i + 1}轮-自由讨论阶段",
                            "system_notice": "进入自由讨论环节。",
                        },
                    ],
                }
            )

    # 投票
    summary_notice = (scenes_result.summary_notice if scenes_result else "") or "请依次总结发言。"
    vote_notice = (scenes_result.vote_notice if scenes_result else "") or "现在进行最终投票。"
    process.append(
        {
            "type": "vote",
            "children": [
                {"stage_title": "总结发言阶段", "system_notice": summary_notice},
                {"stage_title": "最终投票阶段", "system_notice": vote_notice},
            ],
        }
    )

    # 真相揭晓
    truth_notice = (
        scenes_result.truth_reveal_notice if scenes_result else ""
    ) or "游戏结束！揭晓真相..."
    full_truth = (scenes_result.full_truth if scenes_result else "") or ""
    process.append(
        {
            "type": "review",
            "stage_title": "游戏复盘阶段",
            "system_notice": truth_notice,
        }
    )

    process = derive_game_process(process, canonical_clue_stages)
    return process, free_speech_limits, full_truth, truth_notice, canonical_clue_stages


async def _run_metadata(base_llm, script_id: str, state: ScriptGenState):
    """并行任务：生成元数据"""
    _update_convert_task(script_id, "metadata", "running")
    try:
        result = ScriptMetadata.model_validate((await public_bundle(base_llm, state)).model_dump())
        if result:
            _update_convert_task(script_id, "metadata", "complete")
            return result
        else:
            logger.error("metadata: LLM returned None")
            _update_convert_task(script_id, "metadata", "failed")
            return None
    except Exception as e:
        raise_for_inference_recovery(e)
        logger.error(f"metadata failed: {e}", exc_info=True)
        _update_convert_task(script_id, "metadata", "failed", task_failure_reason(e))
        return None


async def _run_character(
    base_llm,
    script_id: str,
    char: dict,
    state: ScriptGenState,
    chars_summary: str,
) -> tuple[str, SingleCharacterResult | None]:
    """并行任务：生成单个角色数据。返回 (name, result)"""
    char_name = char.get("name", "未知")
    task_id = character_task_id(char)
    _update_convert_task(script_id, task_id, "running")
    try:
        identity = {
            key: char[key]
            for key in ("name", "gender", "age", "occupation")
            if char.get(key) is not None
        }
        names = [c["name"] for c in state["disclosure_plan"]["characters"]]
        personal, public = await gather_inference(
            cached_output(
                state,
                f"personal:{char['character_id']}",
                PersonalScript,
                {"角色": identity, **audience_material(state, role=char_name)},
                lambda: invoke(
                    base_llm,
                    PersonalScript,
                    _character_prompt(char_name)
                    + "\n本次只写个人剧本。通常400至600字，亲历充足时适度扩展。材料按本人开局所知筛选，不能补充其他事实，也不能用否定句透露他人未知秘密。不得以全知视角解释他人的心理、动机或私下经历；对他人的判断只能来自本人见闻。保留全部本人实际行为。",
                    {"角色": identity, **audience_material(state, role=char_name)},
                    validate=lambda value: validate_no_secret_inventory(
                        value.character_script, char_name, names
                    ),
                ),
            ),
            public_character(base_llm, state, char, _character_prompt("各角色")),
        )
        derived = await cached_output(
            state,
            f"reading:{char['character_id']}",
            RoleReading,
            {"角色": identity, "个人剧本": personal.character_script},
            lambda: invoke(
                base_llm,
                RoleReading,
                "仅从个人稿派生角色速览（约150–300字，禁止全文复述）和AI扮演资料，不能补充外部事实。保留本人关键行为和作案记忆；"
                "不强制加入疑问、指定要问谁、虚构目标或推理结论。速览自然分段，AI资料忠实身份经历与关系。",
                {"角色": identity, "个人剧本": personal.character_script},
                validate=lambda value: validate_no_secret_inventory(
                    value.script_summary + "\n" + value.system_prompt, char_name, names
                ),
            ),
        )
        result = SingleCharacterResult(
            **identity,
            **personal.model_dump(),
            **public.model_dump(exclude={"character_id"}),
            **derived.model_dump(),
        )
        if result:
            result.name = char_name
            _update_convert_task(script_id, task_id, "complete")
            return char_name, result
        else:
            logger.error(f"char '{char_name}': LLM returned None")
            _update_convert_task(script_id, task_id, "failed")
            return char_name, None
    except Exception as e:
        raise_for_inference_recovery(e)
        logger.error(f"char '{char_name}' failed: {e}", exc_info=True)
        _update_convert_task(script_id, task_id, "failed", task_failure_reason(e))
        return char_name, None


# === 主函数 ===


async def convert_to_game_data(state: ScriptGenState) -> dict:
    characters = []  # Always discover from the latest confirmed final, never draft regex output.
    player_count = state.get("player_count", 4)
    num_rounds = state.get("num_clue_rounds", 2)
    script_title = state.get("script_title", "")
    outline = state.get("outline", "")

    script_id = state.get("script_id", str(uuid.uuid4()))
    base_llm = _get_structured_llm()

    import hashlib
    import json

    from app.script_editor.outline.runtime import current_runtime
    from app.script_editor.services.execution import PROMPT_VERSION

    material = {
        key: state.get(key)
        for key in (
            "final_draft",
            "script_title",
            "player_count",
            "num_clue_rounds",
            "difficulty",
            "ending_mode",
            "prompts",
            "refinement",
        )
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                PROMPT_VERSION,
                "conversion-v3-output-cache",
                material,
                state.get("game_data_sections")
                if (state.get("refinement") or {}).get("target") == "review_game_data"
                else None,
            ],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    previous = state.get("convert_cache") or {}
    runtime = current_runtime.get()
    if runtime and runtime.convert_cache.get("fingerprint") == fingerprint:
        previous = runtime.convert_cache
    cache = (
        dict(previous.get("results") or {}) if previous.get("fingerprint") == fingerprint else {}
    )
    _init_convert_progress(
        script_id,
        characters,
        player_count,
        state.get("convert_progress") if previous.get("fingerprint") == fingerprint else None,
    )
    outputs = ConversionCache(fingerprint, cache, runtime)
    state = {**state, "_conversion_outputs": outputs}
    selected = state.get("conversion_retry_task")
    old_failures = {
        task.get("id")
        for phase in (state.get("convert_progress") or {}).get("phases", [])
        for task in phase.get("tasks", [])
        if task.get("status") == "failed"
    }

    def failure():
        message = "部分游戏数据尚未整理完成，已保留成功内容，请重试对应任务。"
        progress = get_convert_progress(script_id) or {}
        return {
            "current_step": STEP_CONVERT,
            "error_message": message,
            "workflow_error": {
                "scope": "task",
                "code": "conversion_incomplete",
                "message": message,
                "retryable": True,
                "task_ids": [
                    t["id"]
                    for p in progress.get("phases", [])
                    for t in p.get("tasks", [])
                    if t.get("status") == "failed"
                ],
            },
            "retry_step": STEP_CONVERT,
            "convert_cache": {"fingerprint": fingerprint, "results": cache},
            "disclosure_cache": state.get("disclosure_cache", {}),
            "convert_progress": progress,
            "conversion_retry_task": None,
            "conversion_metrics": outputs.metrics,
        }

    async def cached(key, factory, schema, validate=lambda value: True, attempts=1):
        if key in cache:
            value = schema.model_validate(cache[key]) if schema else cache[key]
            if validate(value):
                _update_convert_task(script_id, key, "complete")
                return value
        if selected and key in old_failures and key != selected:
            _update_convert_task(script_id, key, "failed")
            return None
        for attempt in range(attempts):
            _update_convert_task(script_id, key, "running")
            try:
                value = await factory()
                if isinstance(value, tuple):
                    value = value[1]
                if value is None or not validate(value):
                    raise ValueError("转换结果不完整")
                cache[key] = value.model_dump() if schema else value
                if runtime:
                    runtime.convert_cache = {"fingerprint": fingerprint, "results": dict(cache)}
                    runtime.queue_progress("convert_cache", runtime.convert_cache)
                    await runtime.drain_progress()
                return value
            except Exception as error:
                raise_for_inference_recovery(error)
                _update_convert_task(script_id, key, "failed", task_failure_reason(error))
                logger.warning(
                    "Conversion task %s attempt %s failed (%s): %s",
                    key,
                    attempt + 1,
                    type(error).__name__,
                    str(error)[:500],
                )
            if attempt < attempts - 1:
                await asyncio.sleep(attempt + 1)
        _update_convert_task(script_id, key, "failed")
        return None

    # === 步骤0: 角色发现（仅在 characters 为空时） ===
    if not characters:
        _update_convert_task(script_id, "discover_chars", "running")
        try:
            discovered = await cached(
                "disclosure",
                lambda: extract_plan(base_llm, state),
                None,
                lambda value: len(value.get("characters", [])) == player_count,
                attempts=1,
            )
            if discovered:
                characters = discovered["characters"]
                for char in characters:
                    char.setdefault(
                        "character_id",
                        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{script_id}:{char['name']}")),
                    )
                state = {**state, "disclosure_plan": discovered}
                _update_convert_task(script_id, "discover_chars", "complete")
                _add_character_tasks(script_id, characters)
            else:
                _update_convert_task(script_id, "discover_chars", "failed")
        except Exception as e:
            raise_for_inference_recovery(e)
            logger.error(f"Character discovery failed: {e}", exc_info=True)
            _update_convert_task(script_id, "discover_chars", "failed")

    chars_summary = _build_characters_summary(characters)

    if len(characters) != player_count:
        return failure()

    def scenes_valid(value):
        return all(
            getattr(value, field, "").strip()
            for field in (
                "opening_notice",
                "summary_notice",
                "vote_notice",
                "truth_reveal_notice",
                "full_truth",
            )
        )

    def clues_valid(value):
        return len(value.clue_stages) == num_rounds and all(
            stage.items
            and all(item.content.strip() and item.summary.strip() for item in stage.items)
            for stage in value.clue_stages
        )

    jobs = [
        cached(
            "game_flow",
            lambda: _run_game_clues(base_llm, script_id, state, chars_summary),
            ClueStagesResult,
            clues_valid,
        ),
        cached(
            "game_scenes",
            lambda: _run_game_scenes(base_llm, script_id, state, chars_summary),
            ScenesResult,
            scenes_valid,
        ),
        cached(
            "metadata",
            lambda: _run_metadata(base_llm, script_id, state),
            ScriptMetadata,
            lambda value: bool(value.overview.strip() and value.description.strip()),
        ),
    ]
    for char in characters:
        jobs.append(
            cached(
                character_task_id(char),
                lambda c=char: _run_character(base_llm, script_id, c, state, chars_summary),
                SingleCharacterResult,
                lambda value, c=char: (
                    value.name == c["name"]
                    and bool(value.character_script.strip() and value.system_prompt.strip())
                ),
            )
        )
    values = await gather_inference(*jobs)
    if any(value is None for value in values):
        return failure()
    results = [
        *values[:3],
        *[(char["name"], value) for char, value in zip(characters, values[3:], strict=True)],
    ]

    # === 收集结果 ===
    clues_result: ClueStagesResult | None = (
        results[0] if not isinstance(results[0], BaseException) else None
    )
    scenes_result: ScenesResult | None = (
        results[1] if not isinstance(results[1], BaseException) else None
    )
    meta_result: ScriptMetadata | None = (
        results[2] if not isinstance(results[2], BaseException) else None
    )

    char_results: list[SingleCharacterResult] = []
    char_mimo_voices: dict[str, str] = {}
    for r in results[3:]:
        if isinstance(r, BaseException):
            logger.error(f"Character task exception: {r}")
            continue
        if r is None:
            continue
        name, char_result = r  # type: ignore[misc]
        if char_result:
            mimo_voice = _assign_mimo_voice(
                char_result.gender
                or next(
                    (c.get("gender", "") for c in characters if c.get("name") == name),
                    "",
                )
            )
            char_mimo_voices[name] = mimo_voice
            char_results.append(char_result)
            step_voice = _validate_step_voice(
                char_result.tts_voice_id or char_result.step_voice_id, char_result.gender
            )
            logger.info(
                f"char '{name}' OK: script={len(char_result.character_script)}chars, "
                f"mimo_voice={mimo_voice}, step_voice={step_voice}"
            )

    logger.info(
        f"convert merge: clues={'OK' if clues_result else 'FAIL'}, "
        f"scenes={'OK' if scenes_result else 'FAIL'}, "
        f"meta={'OK' if meta_result else 'FAIL'}, "
        f"characters={len(char_results)}/{len(characters)} OK"
    )

    # 补全 character_id
    for c in characters:
        if "character_id" not in c:
            c["character_id"] = str(uuid.uuid4())

    # === 拼接 game_full_process ===
    (
        game_full_process,
        free_speech_limits,
        full_truth,
        truth_reveal_notice,
        clue_stages,
    ) = _merge_game_process(
        clues_result,
        scenes_result,
        num_rounds,
        script_title,
        outline,
        script_id,
    )

    # === 元数据 ===
    overview = meta_result.overview if meta_result else ""
    tags = meta_result.tags if meta_result else "AI创作,剧本杀"
    description = meta_result.description if meta_result else ""

    # === character_scripts & system_prompts_map & character_data ===
    character_scripts = {}
    system_prompts_map = {}
    character_data = []
    char_result_map = {r.name: r for r in char_results}

    for c in characters:
        name = c.get("name", "")
        r = char_result_map.get(name)

        if r:
            character_scripts[name] = r.character_script
            system_prompts_map[name] = r.system_prompt
            step_voice = _validate_step_voice(r.tts_voice_id or r.step_voice_id, r.gender)
            character_data.append(
                {
                    "character_id": c["character_id"],
                    "name": r.name,
                    "gender": r.gender,
                    "age": r.age,
                    "occupation": r.occupation,
                    "character_script": r.character_script,
                    "profile": r.profile,
                    "appearance": r.appearance,
                    "system_prompt": r.system_prompt,
                    "script_summary": r.script_summary,
                    "mimo_voice_id": char_mimo_voices.get(
                        name, _assign_mimo_voice(c.get("gender", ""))
                    ),
                    "step_voice_id": step_voice,
                    "tts_voice_id": step_voice,
                    "voice_provider": "minimax"
                    if settings.INFERENCE_BACKEND == "tokendance"
                    else "stepfun",
                }
            )
            c["profile"] = r.profile
            c["appearance"] = r.appearance
            c["gender"] = r.gender
            c["age"] = r.age
            c["occupation"] = r.occupation
        else:
            raise ValueError("角色转换未完成")

    # Branches are authored only in the structured editor. Preserve any saved
    # manual configuration when conversion is explicitly retried.
    ending_config = (state.get("game_data_sections") or {}).get("ending_config")

    game_data_sections = {
        "opening": _extract_opening(game_full_process),
        "clue_stages": clue_stages,
        "truth_reveal": truth_reveal_notice,
        "full_truth": full_truth,
        "ending_config": ending_config,
        "game_flow": game_full_process,
        "free_speech_limits": free_speech_limits,
        "character_scripts": character_scripts,
        "character_data": character_data,
        "tags": tags,
        "overview": overview,
        "description": description,
    }

    logger.info(
        f"game_data_sections: opening={len(game_data_sections['opening'])}, "
        f"game_flow={len(game_full_process)}, "
        f"character_scripts={len(character_scripts)}, "
        f"character_data={len(character_data)}, "
        f"tags={tags}"
    )

    combined_prompt = (
        f"=== 线索阶段 ===\n{CLUES_SYSTEM}\n\n"
        f"=== 场景消息 ===\n{SCENES_SYSTEM}\n\n"
        f"=== 元数据 ===\n{METADATA_SYSTEM}\n\n"
        f"=== 角色生成 ===\n{CHARACTER_SYSTEM}"
    )
    updated_prompts = {
        **state.get("prompts", {}),
        "convert_to_game_data": combined_prompt,
    }

    character_voice_ids = {}
    for c in characters:
        char_id = c.get("character_id", "")
        name = c.get("name", "")
        if char_id:
            # Store step_voice_id in state for DB save
            cd_entry = next((cd for cd in character_data if cd.get("name") == name), {})
            character_voice_ids[char_id] = cd_entry.get(
                "step_voice_id", _fallback_step_voice(c.get("gender", ""))
            )

    # Only mark complete if ALL tasks succeeded
    progress = get_convert_progress(script_id)
    has_failed = any(
        task.get("status") == "failed"
        for phase in (progress or {}).get("phases", [])
        for task in phase.get("tasks", [])
    )

    if not has_failed:
        _mark_convert_complete(script_id)
    else:
        logger.warning(f"Convert has failures for script {script_id}, not marking complete")
        _publish_convert_progress(script_id)

    persisted_progress = get_convert_progress(script_id) or {}

    return {
        "disclosure_plan": state.get("disclosure_plan", {}),
        "disclosure_cache": state.get("disclosure_cache", {}),
        "game_full_process": game_full_process,
        "clue_stages": clue_stages,
        "full_truth": full_truth,
        "ending_config": ending_config,
        "free_speech_limits": free_speech_limits,
        "character_scripts": character_scripts,
        "system_prompts_map": system_prompts_map,
        "game_data_sections": game_data_sections,
        "characters": characters,
        "character_voice_ids": character_voice_ids,
        "prompts": updated_prompts,
        "convert_progress": persisted_progress,
        "convert_cache": {"fingerprint": fingerprint, "results": cache},
        "error_message": "",
        "workflow_error": None,
        "conversion_retry_task": None,
        "conversion_metrics": outputs.metrics,
        "retry_step": "",
        "current_step": STEP_CONVERT,
    }


# === 从 game_full_process 提取旧格式字段（兼容前端 review 面板） ===


def _extract_opening(game_full_process: list[dict[str, Any]]) -> str:
    """从 initial 阶段提取开场 system_notice"""
    for stage in game_full_process:
        if stage.get("type") == "initial":
            return stage.get("system_notice", "")
    return ""


def _extract_clue_stages(
    game_full_process: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从 advancement 阶段提取线索阶段数据"""
    clue_stages = []
    round_num = 0
    for stage in game_full_process:
        if stage.get("type") == "advancement":
            round_num += 1
            children = stage.get("children", [])
            clue_stages.append(
                {
                    "round_number": round_num,
                    "stage_title": (
                        children[0].get("stage_title", f"第{round_num}轮")
                        if children
                        else f"第{round_num}轮"
                    ),
                    "system_notice": (children[0].get("system_notice", "") if children else ""),
                    "discussion_notice": (
                        children[1].get("system_notice", "") if len(children) > 1 else ""
                    ),
                    "free_speech_limit": 2,
                }
            )
    return clue_stages


def _extract_truth_reveal(game_full_process: list[dict[str, Any]]) -> str:
    """从 review 阶段提取真相揭晓 system_notice"""
    for stage in game_full_process:
        if stage.get("type") == "review":
            return stage.get("system_notice", "")
    return ""


def _generate_fallback_prompts(characters: list[dict], character_scripts: dict) -> dict[str, str]:
    prompts = {}
    for c in characters:
        name = c.get("name", "")
        script = character_scripts.get(name, "")
        prompt_text = f"""你正在扮演剧本杀游戏中的角色「{name}」。

【角色身份】
{name}，{c.get("gender", "")}，{c.get("age", "")}岁，{c.get("occupation", "")}

【核心背景】
{c.get("profile", "") or script[:500] if script else ""}

【你的目标】
1. 隐藏自己的秘密和可疑行为
2. 分析线索，推理真凶
3. 在不暴露自己的前提下，引导讨论方向

【你掌握的关键信息】
{script[:800] if script else "（暂无详细信息）"}
"""
        prompts[name] = prompt_text
    return prompts
