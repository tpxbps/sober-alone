"""
save_to_database node — 保存到数据库
generate_assets node — 生成图片、语音、向量数据（带细粒度进度跟踪）
"""

import json
import logging
import uuid

from app.core.config import settings
from app.script_editor.services.progress_registry import asset_progress_registry
from app.script_editor.state import STEP_GENERATE_ASSETS, STEP_SAVE, ScriptGenState

logger = logging.getLogger(__name__)


def _calc_estimated_duration(state: ScriptGenState) -> int:
    """Calculate estimated game duration in minutes, matching the frontend formula."""
    players = state.get("player_count", 4)
    difficulty = state.get("difficulty", 1)
    rounds = state.get("num_clue_rounds", 2)
    base = 15 + (players - 3) * 10
    diff_mult = {1: 1.0, 2: 1.2, 3: 1.5, 4: 1.8}.get(difficulty, 1.0)
    return round(base * diff_mult + (rounds - 1) * 15)


# === 细粒度进度跟踪 ===


def register_script_thread(script_id: str, thread_id: str):
    """由 API 层调用，注册 script_id → thread_id 映射"""
    asset_progress_registry.register_thread(script_id, thread_id)


def _init_asset_progress(script_id: str, phases: list[dict]):
    """初始化任务树，所有任务为 pending 状态"""
    asset_progress_registry.init(script_id, phases)
    _publish_asset_progress(script_id)


def _update_task_status(script_id: str, task_id: str, status: str, reason: str = ""):
    """更新单个任务状态"""
    asset_progress_registry.update_task(script_id, task_id, status, reason)
    _publish_asset_progress(script_id)


def _mark_progress_complete(script_id: str):
    """标记所有进度为完成"""
    asset_progress_registry.mark_complete(script_id)
    _publish_asset_progress(script_id)


def get_asset_progress(script_id: str) -> dict | None:
    """获取资产生成进度"""
    return asset_progress_registry.snapshot(script_id)


def _publish_asset_progress(script_id: str):
    """通过 SSE 发布 asset 进度"""
    asset_progress_registry.publish(script_id)


# === save_to_database (先于 generate_assets，在安全审查通过后) ===


async def save_to_database(state: ScriptGenState) -> dict:
    """将最终数据保存到数据库"""
    import re

    import aiosqlite

    from app.core.config import settings

    script_id = state.get("script_id", str(uuid.uuid4()))
    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")

    # 从 game_data_sections 中获取用户可能编辑过的数据
    game_data_sections = state.get("game_data_sections", {})

    # 优先使用 game_data_sections 中的数据（用户可能编辑过）
    game_full_process = game_data_sections.get("game_flow", state.get("game_full_process", []))
    full_truth = game_data_sections.get("full_truth", state.get("full_truth", ""))
    free_speech_limits = game_data_sections.get(
        "free_speech_limits", state.get("free_speech_limits", [2, 2])
    )
    character_scripts = game_data_sections.get(
        "character_scripts", state.get("character_scripts", {})
    )
    character_data_list = game_data_sections.get("character_data", [])

    # 构建 character_data 映射（convert 使用 "name" 字段）
    char_data_map = {}
    for cd in character_data_list:
        name = cd.get("name", "") or cd.get("character_name", "")
        if name:
            char_data_map[name] = cd

    # overview: 优先使用 game_data_sections（由 metadata LLM 生成），否则从大纲提取
    overview = game_data_sections.get("overview", "")
    if not overview:
        outline_raw = state.get("outline", "")
        overview = re.sub(r"#{1,6}\s+", "", outline_raw)
        overview = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", overview)
        overview = re.sub(r"[`*\[\]()>_~|]", "", overview)
        overview = overview.strip()[:300]

    # description: 优先使用 game_data_sections.description
    description = game_data_sections.get("description", "") or game_data_sections.get(
        "opening", state.get("final_draft", "")
    )

    # tags: 使用 AI 生成的标签
    tags = game_data_sections.get("tags", "AI创作,剧本杀")

    try:
        async with aiosqlite.connect(db_path) as db:
            # 插入 scripts 记录
            await db.execute(
                """INSERT OR REPLACE INTO scripts
                (script_id, title, overview, description, tags, difficulty, player_count,
                 estimated_duration, game_full_process, full_truth, cover_image_url,
                 free_speech_limits, is_ai_generated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    script_id,
                    state.get("script_title", "未命名剧本"),
                    overview,
                    description,
                    tags,
                    state.get("difficulty", 1),
                    state.get("player_count", 4),
                    _calc_estimated_duration(state),
                    json.dumps(game_full_process, ensure_ascii=False),
                    full_truth,
                    state.get("cover_image_url", ""),
                    json.dumps(free_speech_limits),
                    1,  # is_ai_generated
                ),
            )

            # 插入 characters 记录
            characters = state.get("characters", [])
            if not characters and character_data_list:
                characters = []
                for cd in character_data_list:
                    characters.append(
                        {
                            "character_id": str(uuid.uuid4()),
                            "name": cd.get("name", "") or cd.get("character_name", ""),
                            "gender": cd.get("gender", ""),
                            "age": cd.get("age"),
                            "occupation": cd.get("occupation", ""),
                        }
                    )

            system_prompts = state.get("system_prompts_map", {})
            character_voice_ids = state.get("character_voice_ids", {})

            for c in characters:
                name = c.get("name", "")
                char_id = c.get("character_id", str(uuid.uuid4()))

                cd = char_data_map.get(name, {})
                profile = cd.get("profile", c.get("profile", ""))
                appearance = cd.get("appearance", c.get("appearance", ""))
                system_prompt = cd.get("system_prompt", system_prompts.get(name, ""))
                script_summary = cd.get("script_summary", "")

                char_script = character_scripts.get(name, "") or cd.get("character_script", "")

                if not script_summary and char_script:
                    script_summary = char_script[:200]

                voice_id = cd.get("step_voice_id", "") or character_voice_ids.get(char_id, "")

                await db.execute(
                    """INSERT OR REPLACE INTO characters
                    (script_id, character_id, name, gender, age, occupation,
                     character_script, character_script_summary, profile, appearance,
                     system_prompt, avatar_url, portrait_url, voice_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        script_id,
                        char_id,
                        name,
                        c.get("gender", "") or cd.get("gender", ""),
                        c.get("age") or cd.get("age"),
                        c.get("occupation", "") or cd.get("occupation", ""),
                        char_script,
                        script_summary,
                        profile,
                        appearance,
                        system_prompt,
                        state.get("character_avatars", {}).get(char_id, ""),
                        state.get("character_avatars", {}).get(char_id, ""),
                        voice_id,
                    ),
                )

            await db.commit()

        logger.info(f"Script saved to database: {script_id}")

    except Exception as e:
        logger.error(f"Failed to save script to database: {e}")
        return {
            "current_step": STEP_SAVE,
            "error_message": f"保存失败: {str(e)}",
        }

    return {
        "current_step": STEP_SAVE,
    }


# === generate_assets (在 save_to_database 之后) ===


async def generate_assets(state: ScriptGenState) -> dict:
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

    await _update_asset_urls(script_id, cover_url, avatars, state)

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


async def _update_asset_urls(script_id: str, cover_url: str, avatars: dict, state: ScriptGenState):
    """资源生成完成后，更新数据库中的图片 URL"""
    import aiosqlite

    from app.core.config import settings

    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")

    try:
        async with aiosqlite.connect(db_path) as db:
            # 更新封面图
            if cover_url:
                await db.execute(
                    "UPDATE scripts SET cover_image_url = ? WHERE script_id = ?",
                    (cover_url, script_id),
                )

            # 更新角色头像
            characters = state.get("characters", [])
            game_data_sections = state.get("game_data_sections", {})
            character_data_list = game_data_sections.get("character_data", [])
            if not characters and character_data_list:
                for cd in character_data_list:
                    characters.append(
                        {
                            "character_id": "",
                            "name": cd.get("character_name", ""),
                        }
                    )

            for c in characters:
                char_id = c.get("character_id", "")
                if not char_id:
                    continue
                avatar_url = avatars.get(char_id, "")
                if avatar_url:
                    await db.execute(
                        "UPDATE characters SET avatar_url = ?, portrait_url = ? WHERE character_id = ?",
                        (avatar_url, avatar_url, char_id),
                    )

            await db.commit()
        logger.info(f"Asset URLs updated for script: {script_id}")
    except Exception as e:
        logger.error(f"Failed to update asset URLs: {e}")


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


async def retry_single_asset(script_id: str, task_id: str, state: ScriptGenState):
    """重试单个失败的资产生成任务"""
    characters = state.get("characters", [])

    _update_task_status(script_id, task_id, "running")

    try:
        if task_id == "vectorize_all":
            from app.script_editor.services.chroma_ingest import ingest_script

            ingest_script(
                script_id=script_id,
                characters=characters,
                character_scripts=state.get("character_scripts", {}),
            )

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

        _update_task_status(script_id, task_id, "complete")
        logger.info(f"Asset retry succeeded for task: {task_id}")

        # Check if all tasks are now complete
        _check_and_mark_asset_complete(script_id)

    except Exception as e:
        logger.error(f"Asset retry failed for task {task_id}: {e}")
        _update_task_status(script_id, task_id, "failed")
