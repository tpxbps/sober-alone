"""
BGM预处理脚本 - 调用 MiniMax Music-2.5+ API 生成游戏背景音乐

用法:
    pip install httpx
    python generate_bgm.py --api-key YOUR_MINIMAX_API_KEY
    python generate_bgm.py --api-key xxx --preset lobby       # 只生成大厅
    python generate_bgm.py --api-key xxx --preset vote        # 只生成投票阶段

生成文件 (static/audio/):
    lobby.mp3    - 大厅BGM
    intro.mp3    - 自我介绍阶段
    clue.mp3     - 线索&讨论阶段
    vote.mp3     - 投票&复盘阶段
"""

import argparse
import sys
from pathlib import Path

import httpx

API_URL = "https://api.minimaxi.com/v1/music_generation"


# ============================================================
# 预设提示词
# ============================================================

# V1.0 预设提示词
# LOBBY_PROMPT = (
#     "Instrumental, casual puzzle game lobby, "
#     "light melancholic undertone, cold mysterious atmosphere, "
#     "gentle piano with soft electronic ambient, "
#     "slow tempo, minimalist, slightly dark, cinematic, "
#     "loop-friendly, no drums, subtle tension, "
#     "chillout lounge, ambient noir"
# )
# GAME_PROMPT = (
#     "Instrumental, suspense detective game, "
#     "melancholic and cold atmosphere, "
#     "dark ambient with subtle strings and muted piano, "
#     "medium-slow tempo, mysterious, eerie calm, "
#     "detective noir, psychological thriller, "
#     "loop-friendly, minimalist, cold breeze feeling, "
#     "tension building, unresolved harmony"
# )

PRESETS = {
    # ----------------------------------------------------------
    # 大厅 BGM
    # 灵感: Expedition 33 Lumière 城主题曲
    #       法式手风琴 + 忧郁钢琴 + 轻盈但暗藏悲伤的旋律
    # ----------------------------------------------------------
    "lobby": (
        "Instrumental, French-inspired game lobby theme, "
        "accordion and gentle piano duet, "
        "light melancholic waltz, Belle Époque elegance meets dark mystery, "
        "neoromantic orchestral with soft strings, "
        "slow tempo, graceful but sorrowful undertone, "
        "cinematic, bittersweet, nostalgic Parisian cafe at dusk, "
        "loop-friendly, no percussion, ambient noir, "
        "delicate harp arpeggios, warm yet cold feeling, "
        "like walking through a beautiful but doomed city"
    ),
    # ----------------------------------------------------------
    # 自我介绍阶段 (intro)
    # 舒缓、好奇、初识的宁静感
    # 灵感: Expedition 33 Gustave 主题曲 — 温柔钢琴+弦乐
    # ----------------------------------------------------------
    "intro": (
        "Instrumental, calm and gentle character introduction scene, "
        "solo piano with soft cello accompaniment, "
        "tranquil, contemplative, curious but serene, "
        "neoclassical minimalist, slow arpeggios, "
        "warm strings pad, light as morning mist, "
        "delicate music box texture, intimate chamber music, "
        "loop-friendly, no drums, very soft dynamics, "
        "hopeful melancholy, like meeting strangers who might become friends"
    ),
    # ----------------------------------------------------------
    # 线索&讨论阶段 (clue)
    # 随着游戏推进逐渐紧张，但控制尺度不影响思考
    # 灵感: Expedition 33 探索区 "Cloud Of Anxiety" + "Spring Meadows" 风格
    # ----------------------------------------------------------
    # "clue": (
    #     "Instrumental, quiet suspense deduction, "
    #     "solo muted piano only, occasional pizzicato cello, "
    #     "very slow tempo, lots of silence and space between notes, "
    #     "unresolved harmonies hanging in the air, "
    #     "cold minimalism, Erik Satie meets detective noir, "
    #     "sparse, restrained, each note carefully placed, "
    #     "tension through what is not played, "
    #     "no percussion, no electronic, no marimba, "
    #     "like a single candle flickering in a dark room, "
    #     "loop-friendly, extremely soft dynamics, "
    #     "intellectual calm with underlying unease, "
    #     "ambient noir, breath-like pacing"
    # ),
    # ----------------------------------------------------------
    # 线索&讨论阶段 — 变体 2 (clue_2)
    # 低音单簧管 为主乐器，深沉温暖、无尖锐 attack
    # 主乐器: bass clarinet
    # 意象: 凌晨三点的烟雾缭绕爵士吧，比原版更「沉」更「暗」
    # ----------------------------------------------------------
    "clue": (
        "Instrumental, quiet suspense deduction, "
        "solo bass clarinet, warm breathy low register, "
        "slow tempo, notes smoothly swell and fade, no hard attacks, "
        "dark woody tone blending into silence, "
        "cold minimalism, smoky jazz club at 3am meets detective noir, "
        "sparse, restrained, each phrase a slow exhale, "
        "tension through stillness and patience, "
        "no percussion, no electronic, no marimba, no piano, "
        "like fog settling over a quiet harbor, "
        "loop-friendly, extremely soft dynamics, "
        "intellectual calm with brooding unease, "
        "ambient noir, legato throughout"
    ),
    # ----------------------------------------------------------
    # 线索&讨论阶段 — 变体 3 (clue_3)
    # 古典吉他/Nylon-string guitar 为主乐器，私密不安感
    # 主乐器: nylon-string classical guitar
    # 意象: 空庭院独奏，比原版更「近」更「私」
    # ----------------------------------------------------------
    # "clue": (
    #     "Instrumental, quiet suspense deduction, "
    #     "solo nylon-string classical guitar, "
    #     "slow tempo, notes left hanging in midair, "
    #     "gentle fret creaks and finger slides as texture, "
    #     "unresolved modal harmonies, flamenco melancholy tamed to whisper, "
    #     "cold minimalism, Alhambra at midnight meets detective noir, "
    #     "sparse, restrained, each pluck deliberate and questioning, "
    #     "tension through silence between phrases, "
    #     "no percussion, no electronic, no marimba, "
    #     "like a lone guitarist playing in an empty courtyard, "
    #     "loop-friendly, extremely soft dynamics, "
    #     "intellectual calm with hidden sorrow, "
    #     "ambient noir, meditative pacing"
    # ),
    # ----------------------------------------------------------
    # 投票&复盘阶段 (vote)
    # 真相大白、舒缓、委屈悲伤、淡淡的遗憾
    # 安静地接受残酷事实
    # 灵感: Expedition 33 "Lumière s'éteint" + "Aux Lendemains non Écrits"
    # ----------------------------------------------------------
    "vote": (
        "Instrumental, gentle and sorrowful truth revealed, "
        "solo piano playing a quiet resigned melody, "
        "soft cello and viola weaving beneath, "
        "restrained slow tempo, delicate and fragile, "
        "truth unveiled not with thunder but with silence, "
        "gentle strings like a sigh, no brass, no timpani, "
        "feeling of injustice, quiet grief, innocent blamed, "
        "bittersweet acceptance, like rain falling on an empty street at night, "
        "neoromantic chamber music, intimate and vulnerable, "
        "loop-friendly, minimal dynamics, "
        "like watching something beautiful dissolve, tender melancholy"
    ),
}

OUTPUT_DIR = Path("static/audio")


def generate(api_key: str, preset: str, prompt: str) -> bool:
    output_path = OUTPUT_DIR / f"{preset}.mp3"
    if output_path.exists():
        print(f"[{preset}] 已存在，跳过: {output_path}")
        return True

    print(f"[{preset}] 正在生成...")
    print(f"  prompt: {prompt[:100]}...")

    body = {
        "model": "music-2.5+",
        "prompt": prompt,
        "is_instrumental": True,
        "output_format": "hex",
        "audio_setting": {
            "sample_rate": 44100,
            "bitrate": 256000,
            "format": "mp3",
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(API_URL, json=body, headers=headers, timeout=180)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        print(f"  HTTP错误: {e.response.status_code}")
        print(f"  {e.response.text[:500]}")
        return False
    except Exception as e:
        print(f"  请求失败: {e}")
        return False

    status = data.get("base_resp", {}).get("status_code")
    if status != 0:
        msg = data.get("base_resp", {}).get("status_msg", "")
        print(f"  API错误 ({status}): {msg}")
        return False

    audio_hex = data.get("data", {}).get("audio")
    if not audio_hex:
        print("  无音频数据返回")
        return False

    audio_bytes = bytes.fromhex(audio_hex)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    duration_sec = data.get("extra_info", {}).get("music_duration", 0) / 1000
    print(f"  完成: {output_path} ({len(audio_bytes)/1024:.0f}KB, {duration_sec:.0f}s)")
    return True


def main():
    all_presets = list(PRESETS.keys())
    parser = argparse.ArgumentParser(description="生成游戏BGM")
    parser.add_argument("--api-key", required=True, help="MiniMax API Key")
    parser.add_argument(
        "--preset",
        choices=all_presets + ["all"],
        default="all",
        help="生成哪个预设 (默认all)",
    )
    args = parser.parse_args()

    presets = all_presets if args.preset == "all" else [args.preset]

    results = {}
    for name in presets:
        ok = generate(args.api_key, name, PRESETS[name])
        results[name] = ok

    print("\n--- 结果 ---")
    for name, ok in results.items():
        status = "成功" if ok else "失败"
        path = OUTPUT_DIR / f"{name}.mp3"
        print(f"  {name}: {status}  -> {path}")

    if all(results.values()):
        print(f"\n全部完成！生成 {len(results)} 个音频文件到 {OUTPUT_DIR}/")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
