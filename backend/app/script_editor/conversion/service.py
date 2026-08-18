"""Conversion orchestration behind the LangGraph node facade."""

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.script_editor.conversion.contracts import (
    CharacterDiscoveryResult,
    ClueStagesResult,
    ScenesResult,
    ScriptMetadata,
    SingleCharacterResult,
)
from app.script_editor.conversion.progress import (
    _add_character_tasks,
    _init_convert_progress,
    _mark_convert_complete,
    _publish_convert_progress,
    _update_convert_task,
    get_convert_progress,
)
from app.script_editor.conversion.prompts import (
    CHARACTER_SYSTEM,
    CLUES_SYSTEM,
    DISCOVER_SYSTEM,
    METADATA_SYSTEM,
    SCENES_SYSTEM,
)
from app.script_editor.services.progress_registry import convert_progress_registry
from app.script_editor.state import STEP_CONVERT, ScriptGenState

logger = logging.getLogger(__name__)


def _get_structured_llm():
    from app.core.llm_factory import create_llm

    return create_llm(
        model="deepseek-v4-flash",
        temperature=0.5,
        timeout=180,
        max_retries=2,
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


async def _discover_characters(
    final_draft: str, player_count: int, max_retries: int = 3
) -> list[dict]:
    """从终稿中提取角色列表（当 characters 为空时的降级方案）

    带有严格验证：识别出的角色数量必须等于 player_count，否则重试。
    """
    base_llm = _get_structured_llm()
    llm = base_llm.with_structured_output(
        CharacterDiscoveryResult, method="function_calling", tool_choice="auto"
    )

    user_prompt = (
        f"【关键约束】你必须返回恰好 {player_count} 个角色，不能多也不能少。\n\n"
        f"从以下剧本终稿中，找出所有 {player_count} 个可扮演的角色。\n"
        "对每个角色，提取姓名、性别（男/女）、年龄、职业/身份。\n"
        "请逐段仔细检查全文，确保不遗漏任何一个角色。\n\n"
        f"剧本终稿：\n---\n{final_draft}\n---"
    )

    for attempt in range(max_retries):
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=DISCOVER_SYSTEM),
                    HumanMessage(content=user_prompt),
                ]
            ),
            timeout=120,
        )

        if not result or not getattr(result, "characters", None):
            logger.warning(f"Character discovery attempt {attempt + 1}: returned empty")
            continue

        # Pydantic 级别验证
        if isinstance(result, CharacterDiscoveryResult) and not result.validate_count(player_count):
            logger.warning(
                f"Character discovery attempt {attempt + 1}: "
                f"Pydantic validation failed, found {result.count}, expected {player_count}"
            )
            continue

        discovered = []
        for c in result.characters:  # type: ignore[union-attr]
            discovered.append(
                {
                    "name": c.name.strip(),
                    "gender": c.gender,
                    "age": c.age,
                    "occupation": c.occupation,
                    "character_id": str(uuid.uuid4()),
                    "profile": "",
                    "appearance": "",
                }
            )

        if len(discovered) == player_count:
            logger.info(
                f"Character discovery OK ({attempt + 1} attempts): "
                f"{[c['name'] for c in discovered]}"
            )
            return discovered

        logger.warning(
            f"Character discovery attempt {attempt + 1}: found {len(discovered)}, "
            f"expected {player_count}. Retrying..."
        )

    logger.error(
        f"Character discovery failed after {max_retries} attempts: "
        f"could not find exactly {player_count} characters"
    )
    return []


# === 并行 LLM 调用封装 ===


async def _run_game_clues(base_llm, script_id: str, state: ScriptGenState, chars_summary: str):
    """并行任务：生成线索阶段数据"""
    _update_convert_task(script_id, "game_flow", "running")
    num_rounds = state.get("num_clue_rounds", 2)
    try:
        llm = base_llm.with_structured_output(
            ClueStagesResult, method="function_calling", tool_choice="auto"
        )
        user_msg = (
            f"## 剧本标题\n{state.get('script_title', '')}\n\n"
            f"## 角色列表（{state.get('player_count', 4)}人）\n{chars_summary}\n\n"
            f"## 终稿全文\n---\n{state.get('final_draft', '')}\n---\n\n"
            f"请设计恰好 {num_rounds} 轮线索发现阶段。"
        )
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=CLUES_SYSTEM.format(num_rounds=num_rounds)),
                    HumanMessage(content=user_msg),
                ]
            ),
            timeout=300,
        )
        if result:
            _update_convert_task(script_id, "game_flow", "complete")
            return result
        else:
            logger.error("game_clues: LLM returned None")
            _update_convert_task(script_id, "game_flow", "failed")
            return None
    except Exception as e:
        logger.error(f"game_clues failed: {e}", exc_info=True)
        _update_convert_task(script_id, "game_flow", "failed")
        return None


async def _run_game_scenes(base_llm, script_id: str, state: ScriptGenState, chars_summary: str):
    """并行任务：生成开场/投票/真相等非线索场景"""
    _update_convert_task(script_id, "game_scenes", "running")
    try:
        llm = base_llm.with_structured_output(
            ScenesResult, method="function_calling", tool_choice="auto"
        )
        user_msg = (
            f"## 剧本标题\n{state.get('script_title', '')}\n\n"
            f"## 角色列表（{state.get('player_count', 4)}人）\n{chars_summary}\n\n"
            f"## 终稿全文\n---\n{state.get('final_draft', '')}\n---\n\n"
            f"请生成开场、投票和真相揭晓的系统消息。"
        )
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=SCENES_SYSTEM),
                    HumanMessage(content=user_msg),
                ]
            ),
            timeout=300,
        )
        if result:
            _update_convert_task(script_id, "game_scenes", "complete")
            return result
        else:
            logger.error("game_scenes: LLM returned None")
            _update_convert_task(script_id, "game_scenes", "failed")
            return None
    except Exception as e:
        logger.error(f"game_scenes failed: {e}", exc_info=True)
        _update_convert_task(script_id, "game_scenes", "failed")
        return None


def _merge_game_process(
    clues_result: ClueStagesResult | None,
    scenes_result: ScenesResult | None,
    num_rounds: int,
    script_title: str,
    outline: str,
) -> tuple[list[dict[str, Any]], list[int], str, str]:
    """
    将线索和场景结果按固定模板拼接为完整的 game_full_process。
    返回 (game_full_process, free_speech_limits, full_truth, truth_reveal_notice)
    """
    # 开场
    opening_notice = scenes_result.opening_notice if scenes_result else ""
    if not opening_notice and outline:
        opening_notice = f"故事背景：**【{script_title}】**\n\n{outline}"

    process: list[dict[str, Any]] = [
        {
            "type": "initial",
            "stage_title": "自我介绍阶段",
            "system_notice": opening_notice,
        },
    ]

    # 线索轮次
    free_speech_limits = [2] * num_rounds
    if clues_result:
        clue_stages = clues_result.clue_stages or []
        if clues_result.free_speech_limits:
            free_speech_limits = _clamp_free_speech_limits(
                clues_result.free_speech_limits, num_rounds
            )
        for i in range(num_rounds):
            stage_data = clue_stages[i] if i < len(clue_stages) else None
            clue_notice = (
                stage_data.clue_analysis_notice
                if stage_data and stage_data.clue_analysis_notice
                else f"第{i + 1}轮线索发现！请分析线索。"
            )
            discuss_notice = (
                stage_data.free_discussion_notice
                if stage_data and stage_data.free_discussion_notice
                else "进入自由讨论环节。"
            )
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
                            "system_notice": f"第{i + 1}轮线索发现！请分析线索。",
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

    return process, free_speech_limits, full_truth, truth_notice


async def _run_metadata(base_llm, script_id: str, state: ScriptGenState):
    """并行任务：生成元数据"""
    _update_convert_task(script_id, "metadata", "running")
    try:
        llm = base_llm.with_structured_output(
            ScriptMetadata, method="function_calling", tool_choice="auto"
        )
        user_msg = (
            f"## 剧本标题\n{state.get('script_title', '')}\n\n"
            f"## 终稿概要\n---\n{state.get('final_draft', '')[:1500]}\n---\n\n"
            f"## 大纲\n---\n{state.get('outline', '')[:800]}\n---\n\n"
            f"请生成概述、标签和描述。"
        )
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=METADATA_SYSTEM),
                    HumanMessage(content=user_msg),
                ]
            ),
            timeout=120,
        )
        if result:
            _update_convert_task(script_id, "metadata", "complete")
            return result
        else:
            logger.error("metadata: LLM returned None")
            _update_convert_task(script_id, "metadata", "failed")
            return None
    except Exception as e:
        logger.error(f"metadata failed: {e}", exc_info=True)
        _update_convert_task(script_id, "metadata", "failed")
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
    task_id = f"char_{char_name}"
    _update_convert_task(script_id, task_id, "running")
    try:
        llm = base_llm.with_structured_output(
            SingleCharacterResult, method="function_calling", tool_choice="auto"
        )
        user_msg = (
            f"## 剧本标题\n{state.get('script_title', '')}\n\n"
            f"## 所有角色（{state.get('player_count', 4)}人）\n{chars_summary}\n\n"
            f"## 当前要生成的角色\n"
            f"姓名：{char_name}\n性别：{char.get('gender', '')}\n"
            f"年龄：{char.get('age', '')}\n职业：{char.get('occupation', '')}\n\n"
            f"## 终稿全文\n---\n{state.get('final_draft', '')}\n---\n\n"
            f"请为角色「{char_name}」生成完整数据。"
        )
        result = await asyncio.wait_for(
            llm.ainvoke(
                [
                    SystemMessage(content=CHARACTER_SYSTEM.format(char_name=char_name)),
                    HumanMessage(content=user_msg),
                ]
            ),
            timeout=240,
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
        logger.error(f"char '{char_name}' failed: {e}", exc_info=True)
        _update_convert_task(script_id, task_id, "failed")
        return char_name, None


# === 主函数 ===


async def convert_to_game_data(state: ScriptGenState) -> dict:
    characters = list(state.get("characters", []))
    player_count = state.get("player_count", 4)
    num_rounds = state.get("num_clue_rounds", 2)
    final_draft = state.get("final_draft", "")
    script_title = state.get("script_title", "")
    outline = state.get("outline", "")

    script_id = state.get("script_id", str(uuid.uuid4()))
    _init_convert_progress(script_id, characters, player_count)
    base_llm = _get_structured_llm()

    # === 步骤0: 角色发现（仅在 characters 为空时） ===
    if not characters:
        _update_convert_task(script_id, "discover_chars", "running")
        try:
            discovered = await _discover_characters(final_draft, player_count)
            if discovered:
                characters = discovered
                _update_convert_task(script_id, "discover_chars", "complete")
                _add_character_tasks(script_id, characters)
            else:
                _update_convert_task(script_id, "discover_chars", "failed")
        except Exception as e:
            logger.error(f"Character discovery failed: {e}", exc_info=True)
            _update_convert_task(script_id, "discover_chars", "failed")

    chars_summary = _build_characters_summary(characters)

    if len(characters) != player_count:
        logger.warning(f"Character count ({len(characters)}) != player_count ({player_count})")

    # === 并行调用：clues + scenes + metadata + 所有角色 ===
    coroutines = []

    # 线索
    coroutines.append(_run_game_clues(base_llm, script_id, state, chars_summary))
    # 开场/投票/真相
    coroutines.append(_run_game_scenes(base_llm, script_id, state, chars_summary))
    # metadata
    coroutines.append(_run_metadata(base_llm, script_id, state))

    # characters — stagger by 0.3s to avoid rate limiting
    for i, c in enumerate(characters):

        async def _staggered_char(idx=i, char=c):
            await asyncio.sleep(idx * 0.3)
            return await _run_character(base_llm, script_id, char, state, chars_summary)

        coroutines.append(_staggered_char())

    results = await asyncio.gather(*coroutines, return_exceptions=True)

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
            step_voice = _validate_step_voice(char_result.step_voice_id, char_result.gender)
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
    game_full_process, free_speech_limits, full_truth, truth_reveal_notice = _merge_game_process(
        clues_result,
        scenes_result,
        num_rounds,
        script_title,
        outline,
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
            step_voice = _validate_step_voice(r.step_voice_id, r.gender)
            character_data.append(
                {
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
                }
            )
            c["profile"] = r.profile
            c["appearance"] = r.appearance
            c["gender"] = r.gender
            c["age"] = r.age
            c["occupation"] = r.occupation
        else:
            gender = c.get("gender", "")
            character_data.append(
                {
                    "name": name,
                    "gender": gender,
                    "age": c.get("age"),
                    "occupation": c.get("occupation", ""),
                    "character_script": "",
                    "profile": "",
                    "appearance": "",
                    "system_prompt": "",
                    "mimo_voice_id": _assign_mimo_voice(gender),
                    "step_voice_id": _fallback_step_voice(gender),
                }
            )

    if not system_prompts_map:
        system_prompts_map = _generate_fallback_prompts(characters, character_scripts)

    game_data_sections = {
        "opening": _extract_opening(game_full_process),
        "clue_stages": _extract_clue_stages(game_full_process),
        "truth_reveal": truth_reveal_notice,
        "full_truth": full_truth,
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

    return {
        "game_full_process": game_full_process,
        "full_truth": full_truth,
        "free_speech_limits": free_speech_limits,
        "character_scripts": character_scripts,
        "system_prompts_map": system_prompts_map,
        "game_data_sections": game_data_sections,
        "characters": characters,
        "character_voice_ids": character_voice_ids,
        "prompts": updated_prompts,
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


# === 单任务重试 ===


async def retry_single_convert(script_id: str, task_id: str, state: ScriptGenState):
    """重试单个失败的 convert 任务。
    Note: _run_* functions already update task status internally.
    """
    try:
        if task_id == "discover_chars":
            discovered = await _discover_characters(
                state.get("final_draft", ""),
                state.get("player_count", 4),
            )
            if discovered:
                _add_character_tasks(script_id, discovered)

        else:
            chars_summary = _build_characters_summary(state.get("characters", []))
            base_llm = _get_structured_llm()

            if task_id == "game_flow":
                await _run_game_clues(base_llm, script_id, state, chars_summary)

            elif task_id == "game_scenes":
                await _run_game_scenes(base_llm, script_id, state, chars_summary)

            elif task_id == "metadata":
                await _run_metadata(base_llm, script_id, state)

            elif task_id.startswith("char_"):
                char_name = task_id[5:]
                char = next(
                    (c for c in state.get("characters", []) if c.get("name") == char_name),
                    None,
                )
                if not char:
                    _update_convert_task(script_id, task_id, "failed")
                    return None
                await _run_character(base_llm, script_id, char, state, chars_summary)

        # Check if all tasks are now complete (only marks done if all are "complete")
        _check_and_mark_convert_complete(script_id)

    except Exception as e:
        logger.error(f"Convert retry failed for task {task_id}: {e}", exc_info=True)
        _update_convert_task(script_id, task_id, "failed")


def _check_and_mark_convert_complete(script_id: str):
    """Check if all convert tasks are complete; if so, mark progress as done."""
    if convert_progress_registry.complete_if_all(script_id, {"complete"}):
        _publish_convert_progress(script_id)


def _create_fallback_process(state: dict[str, Any]) -> list[dict[str, Any]]:
    num_rounds = state.get("num_clue_rounds", 2)
    title = state.get("script_title", "未命名剧本")
    outline = state.get("outline", "")

    process: list[dict[str, Any]] = [
        {
            "type": "initial",
            "stage_title": "自我介绍阶段",
            "system_notice": f"故事背景：**【{title}】**\n\n{outline}",
        },
    ]

    for i in range(num_rounds):
        process.append(
            {
                "type": "advancement",
                "children": [
                    {
                        "stage_title": f"第{i + 1}轮-线索分析阶段",
                        "system_notice": f"第{i + 1}轮线索发现！请分析线索。",
                    },
                    {
                        "stage_title": f"第{i + 1}轮-自由讨论阶段",
                        "system_notice": "进入自由讨论环节。",
                    },
                ],
            }
        )

    process.extend(
        [
            {
                "type": "vote",
                "children": [
                    {
                        "stage_title": "总结发言阶段",
                        "system_notice": "请依次总结发言。",
                    },
                    {
                        "stage_title": "最终投票阶段",
                        "system_notice": "现在进行最终投票。",
                    },
                ],
            },
            {
                "type": "review",
                "stage_title": "游戏复盘阶段",
                "system_notice": "游戏结束！揭晓真相...",
            },
        ]
    )

    return process


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
