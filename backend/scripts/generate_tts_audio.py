"""
音频预处理脚本 - 生成静态 TTS 音频文件

使用 mimo-v2-tts 为以下内容生成音频：
1. 角色个人剧本
2. 系统阶段消息（剧本开场白等）

用法：
    cd backend
    python scripts/generate_tts_audio.py
"""

import asyncio
import sys
import os
import sqlite3
import json

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.tts_service import TTSService


async def generate_character_scripts():
    """为所有角色的个人剧本生成音频"""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "game_data.db",
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT c.character_id, c.name, c.script_id, c.character_script, "
        "s.title FROM characters c JOIN scripts s ON c.script_id = s.script_id"
    )
    characters = cursor.fetchall()
    conn.close()

    print(f"\n=== 生成角色剧本音频 ({len(characters)} 个角色) ===\n")

    for char_id, name, script_id, script_content, script_title in characters:
        if not script_content or not script_content.strip():
            print(f"  [SKIP] {name} ({script_title}): 无剧本内容")
            continue

        # 截断过长文本（TTS 限制）
        max_chars = 2000
        text = script_content.strip()
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            print(f"  [WARN] {name}: 剧本内容过长，截断至 {max_chars} 字")

        style_prompt = f"你是一位专业的有声书朗读者。请用沉稳、神秘的语气朗读这段剧本杀角色剧本，仿佛在讲述一个悬疑故事。语速适中，让听众能清楚理解每一个细节。"

        print(f"  [GEN] {name} ({script_title}): {len(text)} 字...", end=" ", flush=True)
        url = await TTSService.generate_and_save_static(
            text=text,
            style_prompt=style_prompt,
            script_id=script_id,
            audio_type="character_scripts",
            identifier=char_id,
        )
        if url:
            print(f"OK -> {url}")
        else:
            print("FAILED")


async def generate_system_messages():
    """为剧本的系统阶段消息生成音频（包括 children 中的通知）"""
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "game_data.db",
    )
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT script_id, title, game_full_process FROM scripts")
    scripts = cursor.fetchall()
    conn.close()

    print(f"\n=== 生成系统消息音频 ({len(scripts)} 个剧本) ===\n")

    for script_id, title, gfp_raw in scripts:
        if not gfp_raw:
            continue

        gfp = json.loads(gfp_raw) if isinstance(gfp_raw, str) else gfp_raw

        for i, stage in enumerate(gfp):
            style_prompt = (
                "你是一位专业的剧本杀主持人。请用沉稳、略带悬疑的语气朗读这段游戏背景介绍，"
                "营造出紧张的氛围感。语速适中，让玩家能沉浸在故事中。"
            )

            # 生成顶层 system_notice
            notice = stage.get("system_notice", "")
            if notice and notice.strip():
                key = f"stage_{i}"
                print(
                    f"  [GEN] {title} - 阶段{i}: {len(notice)} 字...",
                    end=" ",
                    flush=True,
                )
                url = await TTSService.generate_and_save_static(
                    text=notice.strip(),
                    style_prompt=style_prompt,
                    script_id=script_id,
                    audio_type="system_messages",
                    identifier=key,
                )
                if url:
                    print(f"OK -> {url}")
                else:
                    print("FAILED")

            # 生成 children 中的 system_notice
            children = stage.get("children", [])
            for j, child in enumerate(children):
                child_notice = child.get("system_notice", "")
                if not child_notice or not child_notice.strip():
                    continue

                key = f"stage_{i}_child_{j}"
                print(
                    f"  [GEN] {title} - 阶段{i}.children[{j}]: {len(child_notice)} 字...",
                    end=" ",
                    flush=True,
                )
                url = await TTSService.generate_and_save_static(
                    text=child_notice.strip(),
                    style_prompt=style_prompt,
                    script_id=script_id,
                    audio_type="system_messages",
                    identifier=key,
                )
                if url:
                    print(f"OK -> {url}")
                else:
                    print("FAILED")


async def main():
    print("=" * 60)
    print("TTS 音频预处理脚本")
    print("=" * 60)

    await generate_character_scripts()
    await generate_system_messages()

    print("\n" + "=" * 60)
    print("处理完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
