"""Optional asset-generation orchestration."""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.script_editor.asset_generation.progress import (
    _init_asset_progress,
    _mark_progress_complete,
    _publish_asset_progress,
    _update_task_status,
    get_asset_progress,
)
from app.script_editor.repositories.script_repository import ScriptRepository
from app.script_editor.services.progress_registry import asset_progress_registry
from app.script_editor.state import STEP_GENERATE_ASSETS, ScriptGenState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TaskResult:
    ok: bool
    artifact: Any = None
    error: str = ""


async def _generate_assets(state: ScriptGenState) -> dict:
    """
    并行生成所有资源：向量数据、图片、语音
    三个阶段同时运行，每个阶段内部串行但有独立的进度跟踪
    """
    import asyncio

    script_id = state.get("script_id", str(uuid.uuid4()))
    characters = state.get("characters", [])
    game_full_process = state.get("game_full_process", [])

    # 构建 TTS 系统消息任务（从 game_full_process 动态生成）
    tts_sys_tasks = []
    for i, stage in enumerate(game_full_process):
        stage_type = stage.get("type", "")
        if stage_type == "initial":
            tts_sys_tasks.append(
                {
                    "id": f"tts_sys_{i}",
                    "label": "系统消息音频（开场）",
                    "status": "pending",
                }
            )
        elif stage_type in ("advancement", "vote"):
            children = stage.get("children", [])
            for j, _child in enumerate(children):
                label = f"系统消息音频（第{i}阶段）"
                if stage_type == "advancement":
                    label = "线索分析音频" if j == 0 else "自由讨论音频"
                elif stage_type == "vote":
                    label = "总结发言音频" if j == 0 else "投票环节音频"
                tts_sys_tasks.append(
                    {
                        "id": f"tts_sys_{i}_{j}",
                        "label": label,
                        "status": "pending",
                    }
                )
        elif stage_type == "review":
            tts_sys_tasks.append(
                {
                    "id": f"tts_sys_{i}",
                    "label": "系统消息音频（真相揭晓）",
                    "status": "pending",
                }
            )

    # 构建任务树
    phases = [
        {
            "id": "vectorize",
            "label": "角色剧本向量化",
            "tech": "Embedding",
            "model": "zai-embedding-3",
            "tasks": [
                {
                    "id": "vectorize_all",
                    "label": "向量化所有角色的个人剧本并存入向量数据库",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "image",
            "label": "剧本图片生成",
            "tech": "Text-to-Image",
            "model": "doubao-seedream-4.0",
            "tasks": [
                {"id": "cover", "label": "剧本概览封面", "status": "pending"},
                *[
                    {
                        "id": f"avatar_{c.get('character_id', str(i))}",
                        "label": f"{c.get('name', '?')} 立绘",
                        "status": "pending",
                    }
                    for i, c in enumerate(characters)
                ],
            ],
        },
        {
            "id": "tts",
            "label": "语音资源生成",
            "tech": "Text-to-Speech",
            "model": "mimo-v2.5-tts",
            "tasks": [
                *tts_sys_tasks,
                *[
                    {
                        "id": f"tts_{c.get('character_id', str(i))}",
                        "label": f"{c.get('name', '?')} 个人剧本",
                        "status": "pending",
                    }
                    for i, c in enumerate(characters)
                ],
            ],
        },
    ]

    _init_asset_progress(script_id, phases)

    updates = {
        "current_step": STEP_GENERATE_ASSETS,
        "cover_image_url": "",
        "character_avatars": {},
    }

    def tts_task_callback(task_id: str, status: str, reason: str = ""):
        _update_task_status(script_id, task_id, status, reason)

    phase_jobs = []
    if settings.ZHIPUAI_API_KEY:
        phase_jobs.append(_run_vectorize(script_id, state, characters))
    else:
        _update_task_status(script_id, "vectorize_all", "skipped", "未配置 ZHIPUAI_API_KEY")

    image_task_ids = [
        "cover",
        *[f"avatar_{c.get('character_id', str(i))}" for i, c in enumerate(characters)],
    ]
    if settings.DOUBAO_API_KEY:
        phase_jobs.append(_run_images(script_id, state, characters))
    else:
        for task_id in image_task_ids:
            _update_task_status(script_id, task_id, "skipped", "未配置 DOUBAO_API_KEY")

    tts_task_ids = [task["id"] for task in phases[2]["tasks"]]
    if settings.MIMO_API_KEY:
        phase_jobs.append(_run_tts(script_id, state, characters, tts_task_callback, tts_task_ids))
    else:
        for task_id in tts_task_ids:
            _update_task_status(script_id, task_id, "skipped", "未配置 MIMO_API_KEY")

    results = await asyncio.gather(*phase_jobs, return_exceptions=True)

    # 收集结果
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Asset phase error: {r}")

    # 从图片结果中收集 URLs（通过 _run_images 写入 updates 需要额外处理）
    # 为简化，重新收集图片 URLs
    cover_url = ""
    avatars = {}
    try:
        img_root = settings.image_dir / "scripts"
        cover_path = img_root / script_id / "cover.png"
        if cover_path.exists() and cover_path.stat().st_size > 0:
            cover_url = f"/images/scripts/{script_id}/cover.png"
        for c in characters:
            char_id = c.get("character_id", "")
            if char_id:
                avatar_path = img_root / script_id / "avatars" / f"{char_id}.png"
                if avatar_path.exists() and avatar_path.stat().st_size > 0:
                    avatars[char_id] = f"/images/scripts/{script_id}/avatars/{char_id}.png"
    except Exception as e:
        logger.warning(f"Failed to collect image URLs: {e}")

    updates["cover_image_url"] = cover_url
    updates["character_avatars"] = avatars

    # Check if any tasks failed — don't mark complete if so
    progress = get_asset_progress(script_id)
    task_statuses = [
        task.get("status")
        for phase in (progress or {}).get("phases", [])
        for task in phase.get("tasks", [])
    ]
    has_failed = "failed" in task_statuses
    has_incomplete = any(status not in ("complete", "skipped") for status in task_statuses)

    if not has_failed and not has_incomplete:
        _mark_progress_complete(script_id)
    else:
        logger.warning(
            f"Asset generation has failures for script {script_id}, not marking complete"
        )
        # Still publish the current progress so frontend shows failures
        _publish_asset_progress(script_id)

    try:
        await ScriptRepository.update_asset_urls(script_id, cover_url, avatars, state)
    except Exception as e:
        logger.error(f"Failed to update asset URLs: {e}")

    return updates


async def _run_vectorize(script_id: str, state: ScriptGenState, characters: list):
    """向量嵌入阶段"""
    import asyncio

    _update_task_status(script_id, "vectorize_all", "running")
    await asyncio.sleep(0.1)  # yield to let SSE deliver "running" state
    try:
        from app.script_editor.services.chroma_ingest import ingest_script_async

        await ingest_script_async(
            script_id=script_id,
            characters=characters,
            character_scripts=state.get("character_scripts", {}),
        )
        _update_task_status(script_id, "vectorize_all", "complete")
    except Exception as e:
        logger.error(f"ChromaDB ingestion failed: {e}")
        _update_task_status(script_id, "vectorize_all", "failed")


async def _run_images(script_id: str, state: ScriptGenState, characters: list):
    """图片生成阶段（封面 + 角色头像）— 全部并行"""
    import asyncio

    tasks = []

    # 封面
    tasks.append(
        _run_single_image(
            script_id,
            "cover",
            "generate_cover_image",
            {
                "script_id": script_id,
                "story_synopsis": state.get("final_draft", "")[:500],
                "title": state.get("script_title", ""),
            },
        )
    )

    # 角色头像
    for i, c in enumerate(characters):
        char_id = c.get("character_id", str(i))
        task_id = f"avatar_{char_id}"
        tasks.append(
            _run_single_image(
                script_id,
                task_id,
                "generate_character_avatar",
                {
                    "script_id": script_id,
                    "character_id": char_id,
                    "name": c.get("name", ""),
                    "appearance": c.get("appearance", ""),
                    "gender": c.get("gender", ""),
                },
            )
        )

    await asyncio.gather(*tasks, return_exceptions=True)


async def _run_single_image(script_id: str, task_id: str, func_name: str, func_kwargs: dict):
    """包装单个图片生成协程，带进度跟踪"""
    _update_task_status(script_id, task_id, "running")
    try:
        from app.script_editor.services import image_gen

        func = getattr(image_gen, func_name)
        result = await func(**func_kwargs)
        if result:
            _update_task_status(script_id, task_id, "complete")
        else:
            _update_task_status(script_id, task_id, "failed", "供应商未返回有效图片")
    except Exception as e:
        logger.error(f"Image task {task_id} failed: {e}")
        _update_task_status(script_id, task_id, "failed", str(e))


async def _run_tts(
    script_id: str,
    state: ScriptGenState,
    characters: list,
    task_callback,
    task_ids: list[str],
):
    """TTS 生成阶段"""
    try:
        from app.script_editor.services.tts_gen import generate_script_tts

        await generate_script_tts(
            script_id=script_id,
            character_scripts=state.get("character_scripts", {}),
            characters=characters,
            game_full_process=state.get("game_full_process", []),
            task_callback=task_callback,
        )
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        for task_id in task_ids:
            progress = get_asset_progress(script_id)
            matching = [
                task
                for phase in (progress or {}).get("phases", [])
                for task in phase.get("tasks", [])
                if task.get("id") == task_id
            ]
            if matching and matching[0].get("status") in ("pending", "running"):
                _update_task_status(script_id, task_id, "failed", str(e))


def _check_and_mark_asset_complete(script_id: str):
    """Check if all asset tasks are complete; if so, mark progress as done."""
    if asset_progress_registry.complete_if_all(script_id, {"complete", "skipped"}):
        _publish_asset_progress(script_id)


def _delete_tts_audio(script_id: str, task_id: str):
    """Delete existing TTS audio file for a given task so retry regenerates from scratch."""
    from app.services.tts_service import AUDIO_ROOT

    try:
        if task_id.startswith("tts_sys_"):
            # Parse tts_sys_{i} or tts_sys_{i}_{j} → stage_{i} or stage_{i}_child_{j}
            parts = task_id.split("_")
            stage_idx = parts[2]
            if len(parts) > 3:
                identifier = f"stage_{stage_idx}_child_{parts[3]}"
            else:
                identifier = f"stage_{stage_idx}"
            path = AUDIO_ROOT / "scripts" / script_id / "system_messages" / f"{identifier}.wav"
        elif task_id.startswith("tts_"):
            char_id = task_id[len("tts_") :]
            path = AUDIO_ROOT / "scripts" / script_id / "character_scripts" / f"{char_id}.wav"
        else:
            return

        if path.exists():
            path.unlink()
            logger.info(f"Deleted existing audio for retry: {path}")
    except Exception as e:
        logger.warning(f"Failed to delete audio for task {task_id}: {e}")


async def _retry_single_asset(script_id: str, task_id: str, state: ScriptGenState):
    """重试单个失败的资产生成任务"""
    characters = state.get("characters", [])

    _update_task_status(script_id, task_id, "running")

    try:
        result = TaskResult(ok=False, error=f"未知任务: {task_id}")
        if task_id == "vectorize_all":
            from app.script_editor.services.chroma_ingest import ingest_script

            ingest_script(
                script_id=script_id,
                characters=characters,
                character_scripts=state.get("character_scripts", {}),
            )
            result = TaskResult(ok=True)

        elif task_id == "cover":
            from app.script_editor.services.image_gen import generate_cover_image

            cover_url = await generate_cover_image(
                script_id=script_id,
                story_synopsis=state.get("final_draft", "")[:500],
                title=state.get("script_title", ""),
            )
            if cover_url:
                import aiosqlite

                from app.core.config import settings

                db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
                async with aiosqlite.connect(db_path) as db:
                    await db.execute(
                        "UPDATE scripts SET cover_image_url = ? WHERE script_id = ?",
                        (cover_url, script_id),
                    )
                    await db.commit()
                result = TaskResult(ok=True, artifact=cover_url)
            else:
                result = TaskResult(ok=False, error="供应商未返回有效图片")

        elif task_id.startswith("avatar_"):
            char_id = task_id[len("avatar_") :]
            char = next((c for c in characters if c.get("character_id") == char_id), None)
            if char:
                from app.script_editor.services.image_gen import (
                    generate_character_avatar,
                )

                avatar_url = await generate_character_avatar(
                    script_id=script_id,
                    character_id=char_id,
                    name=char.get("name", ""),
                    appearance=char.get("appearance", ""),
                    gender=char.get("gender", ""),
                )
                if avatar_url:
                    import aiosqlite

                    from app.core.config import settings

                    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
                    async with aiosqlite.connect(db_path) as db:
                        await db.execute(
                            "UPDATE characters SET avatar_url = ?, portrait_url = ? WHERE character_id = ?",
                            (avatar_url, avatar_url, char_id),
                        )
                        await db.commit()
                    result = TaskResult(ok=True, artifact=avatar_url)
                else:
                    result = TaskResult(ok=False, error="供应商未返回有效图片")
            else:
                result = TaskResult(ok=False, error="角色不存在")

        elif task_id.startswith("tts_"):
            # TTS retry — handle both system messages and character scripts
            from app.script_editor.services.tts_gen import (
                generate_single_char_audio,
                generate_single_system_audio,
            )

            # Delete existing audio file to force regeneration
            # (avoid idempotency skip when a bad/corrupt file was written previously)
            _delete_tts_audio(script_id, task_id)

            game_full_process = state.get("game_full_process", [])
            character_scripts = state.get("character_scripts", {})

            if task_id.startswith("tts_sys_"):
                # System message: parse stage index and optional child index
                # IDs: tts_sys_{i} or tts_sys_{i}_{j}
                # File identifiers: stage_{i} or stage_{i}_child_{j}
                parts = task_id.split("_")
                # parts: ["tts", "sys", "{i}"] or ["tts", "sys", "{i}", "{j}"]
                stage_idx = int(parts[2])
                child_idx = int(parts[3]) if len(parts) > 3 else -1

                if stage_idx < len(game_full_process):
                    stage = game_full_process[stage_idx]
                    stage_type = stage.get("type", "")

                    if child_idx >= 0:
                        children = stage.get("children", [])
                        if child_idx < len(children):
                            notice = children[child_idx].get("system_notice", "")
                            identifier = f"stage_{stage_idx}_child_{child_idx}"
                            if notice:
                                await generate_single_system_audio(
                                    script_id,
                                    identifier,
                                    notice,
                                    stage_type,
                                    child_idx,
                                )
                                result = TaskResult(ok=True)
                            else:
                                result = TaskResult(ok=False, error="系统消息为空")
                        else:
                            result = TaskResult(ok=False, error="子阶段不存在")
                    else:
                        notice = stage.get("system_notice", "")
                        identifier = f"stage_{stage_idx}"
                        if notice:
                            await generate_single_system_audio(
                                script_id,
                                identifier,
                                notice,
                                stage_type,
                            )
                            result = TaskResult(ok=True)
                        else:
                            result = TaskResult(ok=False, error="系统消息为空")
                else:
                    result = TaskResult(ok=False, error="阶段不存在")

            elif task_id.startswith("tts_") and not task_id.startswith("tts_sys_"):
                # Character script: task_id is tts_{char_id}
                char_id = task_id[len("tts_") :]
                # Find character info
                char = next((c for c in characters if c.get("character_id") == char_id), None)
                if char:
                    name = char.get("name", "")
                    gender = char.get("gender", "")
                    script_text = character_scripts.get(name, "")
                    if script_text:
                        await generate_single_char_audio(
                            script_id,
                            name,
                            char_id,
                            script_text,
                            gender,
                        )
                        result = TaskResult(ok=True)
                    else:
                        result = TaskResult(ok=False, error="角色剧本为空")
                else:
                    result = TaskResult(ok=False, error="角色不存在")

        if not result.ok:
            _update_task_status(script_id, task_id, "failed", result.error)
            return result

        _update_task_status(script_id, task_id, "complete")
        logger.info(f"Asset retry succeeded for task: {task_id}")

        # Check if all tasks are now complete
        _check_and_mark_asset_complete(script_id)
        return result

    except Exception as e:
        logger.error(f"Asset retry failed for task {task_id}: {e}")
        _update_task_status(script_id, task_id, "failed", str(e))
        return TaskResult(ok=False, error=str(e))


class AssetGenerationService:
    async def generate(self, state: ScriptGenState) -> dict:
        return await _generate_assets(state)

    async def retry(self, script_id: str, task_id: str, state: ScriptGenState):
        return await _retry_single_asset(script_id, task_id, state)
