"""Completed-script hydration, canonicalization, and asset dependency planning."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.db.models import Character, Script
from app.script_editor.state import (
    STEP_NORMALIZE_GAME_DATA,
    STEP_PREPARE_ASSET_PLAN,
    ScriptGenState,
)


def _flow_shape(game_flow: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": stage.get("type", ""),
            "children": len(stage.get("children", [])),
        }
        for stage in game_flow
    ]


def _extract_opening(game_flow: list[dict[str, Any]]) -> str:
    return next(
        (stage.get("system_notice", "") for stage in game_flow if stage.get("type") == "initial"),
        "",
    )


def _extract_truth_reveal(game_flow: list[dict[str, Any]]) -> str:
    return next(
        (stage.get("system_notice", "") for stage in game_flow if stage.get("type") == "review"),
        "",
    )


def _extract_clue_stages(
    game_flow: list[dict[str, Any]], free_speech_limits: list[int]
) -> list[dict[str, Any]]:
    result = []
    for index, stage in enumerate(item for item in game_flow if item.get("type") == "advancement"):
        children = stage.get("children", [])
        result.append(
            {
                "round_number": index + 1,
                "stage_title": (
                    children[0].get("stage_title", f"第{index + 1}轮")
                    if children
                    else f"第{index + 1}轮"
                ),
                "system_notice": children[0].get("system_notice", "") if children else "",
                "discussion_notice": (
                    children[1].get("system_notice", "") if len(children) > 1 else ""
                ),
                "clues": [],
                "free_speech_limit": (
                    free_speech_limits[index] if index < len(free_speech_limits) else 2
                ),
            }
        )
    return result


def hydrate_completed_script(
    script: Script,
    characters: list[Character],
    owner_key_hash: str,
) -> ScriptGenState:
    game_flow = copy.deepcopy(script.game_full_process or [])
    limits = list(script.free_speech_limits or [])
    character_data: list[dict[str, Any]] = []
    character_scripts: dict[str, str] = {}
    state_characters: list[dict[str, Any]] = []
    avatars: dict[str, str] = {}
    voice_ids: dict[str, str] = {}

    for character in characters:
        item = {
            "character_id": character.character_id,
            "name": character.name,
            "gender": character.gender or "",
            "age": character.age,
            "occupation": character.occupation or "",
            "character_script": character.character_script or "",
            "script_summary": character.character_script_summary or "",
            "profile": character.profile or "",
            "appearance": character.appearance or "",
            "system_prompt": character.system_prompt or "",
            "step_voice_id": character.voice_id or "",
        }
        character_data.append(item)
        character_scripts[character.name] = character.character_script or ""
        state_characters.append(copy.deepcopy(item))
        if character.avatar_url:
            avatars[character.character_id] = character.avatar_url
        voice_ids[character.character_id] = character.voice_id or ""

    sections = {
        "title": script.title,
        "difficulty": script.difficulty,
        "player_count": script.player_count,
        "opening": _extract_opening(game_flow),
        "clue_stages": _extract_clue_stages(game_flow, limits),
        "truth_reveal": _extract_truth_reveal(game_flow),
        "full_truth": script.full_truth or "",
        "game_flow": game_flow,
        "free_speech_limits": limits,
        "character_scripts": character_scripts,
        "character_data": character_data,
        "overview": script.overview or "",
        "tags": script.tags or "",
        "description": script.description or "",
    }
    state: ScriptGenState = {
        "workflow_mode": "edit",
        "owner_key_hash": owner_key_hash,
        "script_id": script.script_id,
        "script_title": script.title,
        "difficulty": script.difficulty,
        "player_count": script.player_count,
        "num_clue_rounds": len([s for s in game_flow if s.get("type") == "advancement"]),
        "characters": state_characters,
        "character_scripts": character_scripts,
        "system_prompts_map": {c.name: c.system_prompt or "" for c in characters},
        "character_voice_ids": voice_ids,
        "game_full_process": game_flow,
        "full_truth": script.full_truth or "",
        "free_speech_limits": limits,
        "game_data_sections": sections,
        "cover_image_url": script.cover_image_url or "",
        "character_avatars": avatars,
        "final_draft": "",
        "prompts": {},
        "error_message": "",
        "selected_asset_ids": [],
    }
    state["original_snapshot"] = {
        "character_ids": [c.character_id for c in characters],
        "player_count": script.player_count,
        "flow_shape": _flow_shape(game_flow),
        "asset_dependencies": asset_dependencies(state),
    }
    return state


def normalize_game_data(state: ScriptGenState) -> dict[str, Any]:
    sections = copy.deepcopy(state.get("game_data_sections", {}))
    game_flow = sections.get("game_flow") or []
    character_data = sections.get("character_data") or []
    errors: list[str] = []

    title = str(sections.get("title") or state.get("script_title") or "").strip()
    if not title:
        errors.append("剧本名称不能为空")
    elif len(title) > 200:
        errors.append("剧本名称不能超过 200 个字符")

    try:
        difficulty = int(sections.get("difficulty", state.get("difficulty", 1)))
    except (TypeError, ValueError):
        difficulty = 0
    if difficulty not in (1, 2, 3, 4):
        errors.append("难度必须为 1-4")

    names = [str(item.get("name", "")).strip() for item in character_data]
    if any(not name for name in names):
        errors.append("角色名称不能为空")
    if len(set(names)) != len(names):
        errors.append("角色名称不能重复")

    original = state.get("original_snapshot", {}) if state.get("workflow_mode") == "edit" else {}
    original_ids = list(original.get("character_ids", []))
    current_ids = [str(item.get("character_id", "")) for item in character_data]
    if original_ids and current_ids != original_ids:
        errors.append("编辑完成剧本时不能增删角色或改变角色顺序")
    if original.get("player_count") and len(character_data) != original["player_count"]:
        errors.append("编辑完成剧本时不能修改玩家人数")
    if original.get("flow_shape") and _flow_shape(game_flow) != original["flow_shape"]:
        errors.append("编辑完成剧本时不能增删轮次或改变流程节点类型")

    round_count = len([stage for stage in game_flow if stage.get("type") == "advancement"])
    raw_limits = sections.get("free_speech_limits") or []
    try:
        limits = [int(value) for value in raw_limits]
    except (TypeError, ValueError):
        limits = []
    if len(limits) != round_count or any(value < 1 or value > 3 for value in limits):
        errors.append("每轮自由讨论发言次数必须为 1-3，且数量与轮次一致")

    if errors:
        return {
            "current_step": STEP_NORMALIZE_GAME_DATA,
            "data_validation_errors": errors,
            "_review_action": "invalid",
        }

    previous_by_id = {
        str(item.get("character_id", "")): item for item in state.get("characters", [])
    }
    characters: list[dict[str, Any]] = []
    scripts: dict[str, str] = {}
    prompts: dict[str, str] = {}
    voices: dict[str, str] = {}
    canonical_data: list[dict[str, Any]] = []
    legacy_scripts = sections.get("character_scripts", {}) or {}

    for item in character_data:
        character_id = str(item.get("character_id", ""))
        previous = previous_by_id.get(character_id, {})
        name = str(item.get("name", "")).strip()
        personal_script = str(item.get("character_script", legacy_scripts.get(name, "")) or "")
        canonical = {
            "character_id": character_id,
            "name": name,
            "gender": str(item.get("gender", previous.get("gender", "")) or ""),
            "age": item.get("age", previous.get("age")),
            "occupation": str(item.get("occupation", previous.get("occupation", "")) or ""),
            "character_script": personal_script,
            "script_summary": str(item.get("script_summary", "") or ""),
            "profile": str(item.get("profile", "") or ""),
            "appearance": str(item.get("appearance", "") or ""),
            "system_prompt": str(item.get("system_prompt", "") or ""),
            "step_voice_id": str(item.get("step_voice_id", "") or ""),
        }
        canonical_data.append(canonical)
        characters.append(copy.deepcopy(canonical))
        scripts[name] = personal_script
        prompts[name] = canonical["system_prompt"]
        voices[character_id] = canonical["step_voice_id"]

    sections.update(
        {
            "title": title,
            "difficulty": difficulty,
            "player_count": len(characters),
            "opening": _extract_opening(game_flow),
            "truth_reveal": _extract_truth_reveal(game_flow),
            "clue_stages": _extract_clue_stages(game_flow, limits),
            "character_data": canonical_data,
            "character_scripts": scripts,
            "free_speech_limits": limits,
        }
    )
    return {
        "current_step": STEP_NORMALIZE_GAME_DATA,
        "data_validation_errors": [],
        "_review_action": "confirm",
        "script_title": title,
        "difficulty": difficulty,
        "player_count": len(characters),
        "num_clue_rounds": round_count,
        "game_data_sections": sections,
        "game_full_process": game_flow,
        "full_truth": str(sections.get("full_truth", "") or ""),
        "free_speech_limits": limits,
        "characters": characters,
        "character_scripts": scripts,
        "system_prompts_map": prompts,
        "character_voice_ids": voices,
    }


def _task_dependencies(state: ScriptGenState) -> list[dict[str, Any]]:
    sections = state.get("game_data_sections", {})
    characters = state.get("characters", [])
    scripts = state.get("character_scripts", {})
    tasks: list[dict[str, Any]] = []

    for character in characters:
        cid = character.get("character_id", "")
        name = character.get("name", "")
        tasks.append(
            {
                "id": f"vector_{cid}",
                "phase": "vectorize",
                "label": f"{name} 个人剧本向量化",
                "dependencies": {
                    "character_id": cid,
                    "name": name,
                    "script": scripts.get(name, ""),
                },
            }
        )
    tasks.append(
        {
            "id": "cover",
            "phase": "image",
            "label": "剧本概览封面",
            "dependencies": {
                "title": state.get("script_title", ""),
                "overview": sections.get("overview", ""),
                "description": sections.get("description", ""),
            },
        }
    )
    for character in characters:
        cid = character.get("character_id", "")
        tasks.append(
            {
                "id": f"avatar_{cid}",
                "phase": "image",
                "label": f"{character.get('name', '?')} 立绘",
                "dependencies": {
                    "name": character.get("name", ""),
                    "gender": character.get("gender", ""),
                    "appearance": character.get("appearance", ""),
                },
            }
        )
    for index, stage in enumerate(state.get("game_full_process", [])):
        stage_type = stage.get("type", "")
        if stage_type in ("initial", "review"):
            notice = stage.get("system_notice", "")
            if not notice:
                continue
            tasks.append(
                {
                    "id": f"tts_sys_{index}",
                    "phase": "tts",
                    "label": f"{stage.get('stage_title', '系统消息')} TTS",
                    "dependencies": {
                        "path": f"stage_{index}",
                        "stage_type": stage_type,
                        "text": notice,
                    },
                }
            )
        elif stage_type in ("advancement", "vote"):
            for child_index, child in enumerate(stage.get("children", [])):
                notice = child.get("system_notice", "")
                if not notice:
                    continue
                tasks.append(
                    {
                        "id": f"tts_sys_{index}_{child_index}",
                        "phase": "tts",
                        "label": f"{child.get('stage_title', '系统消息')} TTS",
                        "dependencies": {
                            "path": f"stage_{index}_child_{child_index}",
                            "stage_type": stage_type,
                            "text": notice,
                        },
                    }
                )
    for character in characters:
        cid = character.get("character_id", "")
        name = character.get("name", "")
        tasks.append(
            {
                "id": f"tts_{cid}",
                "phase": "tts",
                "label": f"{name} 个人剧本 TTS",
                "dependencies": {
                    "name": name,
                    "gender": character.get("gender", ""),
                    "script": scripts.get(name, ""),
                },
            }
        )
    return tasks


def asset_dependencies(state: ScriptGenState) -> dict[str, str]:
    return {
        task["id"]: json.dumps(
            task["dependencies"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        for task in _task_dependencies(state)
    }


def _artifact_missing(script_id: str, task_id: str) -> bool:
    if task_id == "cover":
        return not (settings.image_dir / "scripts" / script_id / "cover.png").exists()
    if task_id.startswith("avatar_"):
        cid = task_id.removeprefix("avatar_")
        return not (settings.image_dir / "scripts" / script_id / "avatars" / f"{cid}.png").exists()
    if task_id.startswith("tts_sys_"):
        parts = task_id.split("_")
        identifier = f"stage_{parts[2]}"
        if len(parts) == 4:
            identifier += f"_child_{parts[3]}"
        return not (
            settings.audio_dir / "scripts" / script_id / "system_messages" / f"{identifier}.wav"
        ).exists()
    if task_id.startswith("tts_"):
        cid = task_id.removeprefix("tts_")
        return not (
            settings.audio_dir / "scripts" / script_id / "character_scripts" / f"{cid}.wav"
        ).exists()
    if task_id.startswith("vector_"):
        if not Path(settings.CHROMA_PERSIST_DIR).exists():
            return True
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings

            client = chromadb.PersistentClient(
                path=settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            collection = client.get_collection(f"script_{script_id.replace('-', '_')}")
            result = collection.get(
                where={"character_id": task_id.removeprefix("vector_")},
                limit=1,
            )
            return not bool(result.get("ids"))
        except Exception:
            return True
    return True


def prepare_asset_plan(state: ScriptGenState) -> dict[str, Any]:
    original = state.get("original_snapshot", {}).get("asset_dependencies", {})
    current = asset_dependencies(state)
    script_id = state.get("script_id", "")
    plan = []
    phase_labels = {
        "vectorize": "角色剧本向量化",
        "image": "剧本图片生成",
        "tts": "语音资源生成",
    }
    for task in _task_dependencies(state):
        task_id = task["id"]
        changed = original.get(task_id) != current.get(task_id)
        missing = _artifact_missing(script_id, task_id)
        phase = task["phase"]
        if phase == "vectorize":
            available = bool(settings.ZHIPUAI_API_KEY)
            reason = "未配置 ZHIPUAI_API_KEY"
        elif phase == "image":
            available = bool(settings.DOUBAO_API_KEY)
            reason = "未配置 DOUBAO_API_KEY"
        else:
            available = bool(settings.MIMO_API_KEY)
            reason = "未配置 MIMO_API_KEY"
            if task_id.startswith("tts_") and not task_id.startswith("tts_sys_"):
                if not task["dependencies"].get("script"):
                    available = False
                    reason = "角色个人剧本为空"
        plan.append(
            {
                "id": task_id,
                "phase": phase,
                "phase_label": phase_labels[phase],
                "label": task["label"],
                "changed": changed,
                "missing": missing,
                "available": available,
                "unavailable_reason": "" if available else reason,
                "default_selected": available and (changed or missing),
                "change_reason": (
                    "依赖字段已修改" if changed else "资源文件缺失" if missing else "依赖字段未变化"
                ),
            }
        )
    return {"current_step": STEP_PREPARE_ASSET_PLAN, "asset_plan": plan}
