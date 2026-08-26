"""Persistence boundary for generated scripts and characters."""

import json
import logging
import uuid
from datetime import datetime

from app.core.config import settings
from app.script_editor.state import STEP_SAVE, ScriptGenState

logger = logging.getLogger(__name__)


def _calc_estimated_duration(state: ScriptGenState) -> int:
    """Calculate estimated game duration in minutes, matching the frontend formula."""
    players = state.get("player_count", 4)
    difficulty = state.get("difficulty", 1)
    rounds = state.get("num_clue_rounds", 2)
    base = 15 + (players - 3) * 10
    diff_mult = {1: 1.0, 2: 1.2, 3: 1.5, 4: 1.8}.get(difficulty, 1.0)
    return round(base * diff_mult + (rounds - 1) * 15)


async def _save_generated_script(state: ScriptGenState) -> dict:
    """Persist canonical text first, without replacing parent rows or resources."""
    import re

    import aiosqlite

    script_id = state.get("script_id", str(uuid.uuid4()))
    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")

    game_data_sections = state.get("game_data_sections", {})
    game_full_process = game_data_sections.get("game_flow", state.get("game_full_process", []))
    full_truth = game_data_sections.get("full_truth", state.get("full_truth", ""))
    free_speech_limits = game_data_sections.get(
        "free_speech_limits", state.get("free_speech_limits", [2, 2])
    )
    character_scripts = game_data_sections.get(
        "character_scripts", state.get("character_scripts", {})
    )
    character_data_list = game_data_sections.get("character_data", [])

    char_data_by_id = {
        str(item.get("character_id", "")): item
        for item in character_data_list
        if item.get("character_id")
    }

    overview = game_data_sections.get("overview", "")
    if not overview:
        outline_raw = state.get("outline", "")
        overview = re.sub(r"#{1,6}\s+", "", outline_raw)
        overview = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", overview)
        overview = re.sub(r"[`*\[\]()>_~|]", "", overview)
        overview = overview.strip()[:300]

    description = game_data_sections.get("description", "") or game_data_sections.get(
        "opening", state.get("final_draft", "")
    )
    tags = game_data_sections.get("tags", "AI创作,剧本杀")
    workflow_mode = state.get("workflow_mode", "create")
    characters = list(state.get("characters", []))
    system_prompts = state.get("system_prompts_map", {})
    character_voice_ids = state.get("character_voice_ids", {})

    try:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("BEGIN")
            common_values = (
                state.get("script_title", "未命名剧本"),
                overview,
                description,
                tags,
                state.get("difficulty", 1),
                state.get("player_count", 4),
                _calc_estimated_duration(state),
                json.dumps(game_full_process, ensure_ascii=False),
                full_truth,
                json.dumps(free_speech_limits),
            )
            if workflow_mode == "edit":
                cursor = await db.execute(
                    """UPDATE scripts SET title = ?, overview = ?, description = ?, tags = ?,
                    difficulty = ?, player_count = ?, estimated_duration = ?,
                    game_full_process = ?, full_truth = ?, free_speech_limits = ?
                    WHERE script_id = ?""",
                    (*common_values, script_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("要编辑的剧本不存在")
                rows = await db.execute_fetchall(
                    "SELECT character_id FROM characters WHERE script_id = ? ORDER BY character_id",
                    (script_id,),
                )
                persisted_ids = [row[0] for row in rows]
                submitted_ids = sorted(str(item.get("character_id", "")) for item in characters)
                if persisted_ids != submitted_ids:
                    raise ValueError("角色结构已变化，已拒绝覆盖保存")
            else:
                await db.execute(
                    """INSERT INTO scripts
                    (script_id, title, overview, description, tags, difficulty, player_count,
                     estimated_duration, game_full_process, full_truth, cover_image_url,
                     free_speech_limits, is_ai_generated, owner_key_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        script_id,
                        *common_values[:9],
                        state.get("cover_image_url", ""),
                        common_values[9],
                        1,
                        state.get("owner_key_hash"),
                        datetime.now().isoformat(sep=" "),
                    ),
                )

            for c in characters:
                name = c.get("name", "")
                char_id = c.get("character_id", str(uuid.uuid4()))
                cd = char_data_by_id.get(char_id, c)
                profile = cd.get("profile", c.get("profile", ""))
                appearance = cd.get("appearance", c.get("appearance", ""))
                system_prompt = cd.get("system_prompt", system_prompts.get(name, ""))
                script_summary = cd.get("script_summary", "")

                char_script = character_scripts.get(name, "") or cd.get("character_script", "")

                if not script_summary and char_script:
                    script_summary = char_script[:200]

                voice_id = cd.get("step_voice_id", "") or character_voice_ids.get(char_id, "")

                values = (
                    name,
                    c.get("gender", "") or cd.get("gender", ""),
                    c.get("age") if c.get("age") is not None else cd.get("age"),
                    c.get("occupation", "") or cd.get("occupation", ""),
                    char_script,
                    script_summary,
                    profile,
                    appearance,
                    system_prompt,
                    voice_id,
                )
                if workflow_mode == "edit":
                    cursor = await db.execute(
                        """UPDATE characters SET name = ?, gender = ?, age = ?,
                        occupation = ?, character_script = ?, character_script_summary = ?,
                        profile = ?, appearance = ?, system_prompt = ?, voice_id = ?
                        WHERE script_id = ? AND character_id = ?""",
                        (*values, script_id, char_id),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError(f"角色 {char_id} 不存在")
                else:
                    avatar = state.get("character_avatars", {}).get(char_id, "")
                    await db.execute(
                        """INSERT INTO characters
                        (script_id, character_id, name, gender, age, occupation,
                         character_script, character_script_summary, profile, appearance,
                         system_prompt, avatar_url, portrait_url, voice_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (script_id, char_id, *values[:9], avatar, avatar, values[9]),
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
        "error_message": "",
    }


class ScriptRepository:
    """Persist one generated script and its characters in one SQLite transaction."""

    @staticmethod
    async def save_generated_script(state: ScriptGenState) -> dict:
        return await _save_generated_script(state)

    @staticmethod
    async def update_asset_urls(
        script_id: str,
        cover_url: str,
        avatars: dict[str, str],
        state: ScriptGenState,
    ) -> None:
        """Update generated image URLs without mutating workflow state."""
        import aiosqlite

        db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")
        characters = list(state.get("characters", []))

        async with aiosqlite.connect(db_path) as db:
            if cover_url:
                await db.execute(
                    "UPDATE scripts SET cover_image_url = ? WHERE script_id = ?",
                    (cover_url, script_id),
                )

            for character in characters:
                character_id = character.get("character_id", "")
                avatar_url = avatars.get(character_id, "")
                if character_id and avatar_url:
                    await db.execute(
                        "UPDATE characters SET avatar_url = ?, portrait_url = ? "
                        "WHERE character_id = ?",
                        (avatar_url, avatar_url, character_id),
                    )

            await db.commit()
