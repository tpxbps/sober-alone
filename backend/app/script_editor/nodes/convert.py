"""
convert_to_game_data node — 将终稿转化为结构化游戏数据

步骤0（可选）: 角色发现 — 从终稿中提取角色列表（仅在 characters 为空时执行）
并行调用:
  - game_flow: 完整游戏流程 JSON（含开场/线索/真相 system_notice）+ full_truth + free_speech_limits
  - metadata: overview + tags + description
  - char_N: 逐角色生成完整数据
"""

import asyncio
import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.script_editor.services.progress_registry import convert_progress_registry
from app.script_editor.state import STEP_CONVERT, ScriptGenState

logger = logging.getLogger(__name__)

# === Convert 进度追踪 ===


def register_script_thread(script_id: str, thread_id: str):
    convert_progress_registry.register_thread(script_id, thread_id)


def _init_convert_progress(
    script_id: str,
    characters: list[dict],
    player_count: int,
):
    need_discovery = len(characters) == 0

    char_tasks = []
    if need_discovery:
        char_tasks.append(
            {
                "id": "discover_chars",
                "label": f"从终稿中识别 {player_count} 个角色",
                "status": "pending",
            }
        )
    for i, c in enumerate(characters):
        char_tasks.append(
            {
                "id": f"char_{c.get('name', str(i))}",
                "label": f"{c.get('name', '?')} 完整数据",
                "status": "pending",
            }
        )

    char_label = (
        f"角色数据生成（{len(characters)}人）"
        if characters
        else f"角色识别与数据生成（{player_count}人）"
    )

    phases = [
        {
            "id": "game_flow",
            "label": "线索阶段数据",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "game_flow",
                    "label": "生成线索阶段系统消息",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "game_scenes",
            "label": "开场与真相",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "game_scenes",
                    "label": "生成开场、投票、真相消息",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "metadata",
            "label": "剧本元数据",
            "tech": "LLM",
            "tasks": [
                {
                    "id": "metadata",
                    "label": "生成概述、标签、描述",
                    "status": "pending",
                },
            ],
        },
        {
            "id": "characters",
            "label": char_label,
            "tech": "LLM",
            "tasks": char_tasks,
        },
    ]
    convert_progress_registry.init(script_id, phases)
    _publish_convert_progress(script_id)


def _add_character_tasks(script_id: str, characters: list[dict]):
    """角色发现成功后，动态添加角色任务到进度树"""

    def add_tasks(progress: dict) -> None:
        for phase in progress["phases"]:
            if phase["id"] == "characters":
                phase["label"] = f"角色数据生成（{len(characters)}人）"
                for i, c in enumerate(characters):
                    phase["tasks"].append(
                        {
                            "id": f"char_{c.get('name', str(i))}",
                            "label": f"{c.get('name', '?')} 完整数据",
                            "status": "pending",
                        }
                    )
                break

    convert_progress_registry.mutate(script_id, add_tasks)
    _publish_convert_progress(script_id)


def _update_convert_task(script_id: str, task_id: str, status: str):
    convert_progress_registry.update_task(script_id, task_id, status)
    _publish_convert_progress(script_id)


def _mark_convert_complete(script_id: str):
    convert_progress_registry.mark_complete(script_id)
    _publish_convert_progress(script_id)


def _publish_convert_progress(script_id: str):
    convert_progress_registry.publish(script_id)


def get_convert_progress(script_id: str) -> dict | None:
    return convert_progress_registry.snapshot(script_id)


def reset_convert_progress(script_id: str):
    convert_progress_registry.reset(script_id)


# === Pydantic 结构化输出 Schema ===


class ClueStageItem(BaseModel):
    """单轮线索阶段的结构"""

    clue_analysis_notice: str = Field(
        default="",
        description="线索分析阶段系统消息（含本轮发现的线索描述和分析引导）",
    )
    free_discussion_notice: str = Field(
        default="",
        description="自由讨论阶段系统消息（引导玩家讨论的方向）",
    )


class ClueStagesResult(BaseModel):
    """线索阶段的结构化输出 — 仅包含线索轮次"""

    clue_stages: list[ClueStageItem] = Field(
        default_factory=list,
        description=(
            "恰好 num_rounds 个线索阶段，每个包含 clue_analysis_notice 和 free_discussion_notice"
        ),
    )
    free_speech_limits: list[int] = Field(
        default_factory=list,
        description="每轮自由讨论最大发言次数（1-3的小正整数），长度恰好为线索轮次数",
    )


class ScenesResult(BaseModel):
    """非线索场景的结构化输出 — 开场 + 投票 + 真相"""

    opening_notice: str = Field(
        default="",
        description="游戏开场系统消息（800-1200字），营造悬疑氛围，介绍故事背景",
    )
    summary_notice: str = Field(
        default="",
        description="总结发言阶段系统消息",
    )
    vote_notice: str = Field(
        default="",
        description="投票阶段系统消息",
    )
    truth_reveal_notice: str = Field(
        default="",
        description="真相揭晓系统消息（800-1500字）",
    )
    full_truth: str = Field(
        default="",
        description="完整真相文本（800-1500字），涵盖所有角色的真实动机和作案过程",
    )


class ScriptMetadata(BaseModel):
    overview: str = Field(
        default="",
        description="剧本概述，100-200字的简洁介绍",
    )
    tags: str = Field(
        default="",
        description="3-5个中文标签，逗号分隔",
    )
    description: str = Field(
        default="",
        description="剧本详细描述，用于详情页面展示",
    )


class SingleCharacterResult(BaseModel):
    """单个角色的完整生成结果"""

    name: str = Field(description="角色名（纯中文，2-4个字）")
    gender: str = Field(default="", description="性别：男/女")
    age: int = Field(default=25, description="年龄")
    occupation: str = Field(default="", description="职业/身份")
    character_script: str = Field(
        default="",
        description="第一人称视角的完整个人剧本（1500-3000字）",
    )
    profile: str = Field(
        default="",
        description="角色简介（100-200字，用于角色选择时对玩家展示的模糊概述，不暴露秘密）",
    )
    appearance: str = Field(
        default="",
        description="外貌描述（100-200字，用于AI绘图提示词，包含体型、发型、服装、特征）",
    )
    system_prompt: str = Field(
        default="",
        description="AI扮演该角色的系统提示词",
    )
    script_summary: str = Field(
        default="",
        description="角色剧本摘要（100-200字，概括该角色的核心经历和秘密）",
    )
    step_voice_id: str = Field(
        default="",
        description="为该角色选择最适合的 TTS 音色 ID（从可用音色列表中选取）",
    )


class CharacterBrief(BaseModel):
    """角色发现结果"""

    name: str = Field(description="角色名")
    gender: str = Field(default="", description="性别：男/女")
    age: int = Field(default=25, description="年龄")
    occupation: str = Field(default="", description="职业/身份")


class CharacterDiscoveryResult(BaseModel):
    """角色发现结果 — 使用 model_validator 强制角色数量等于 player_count"""

    characters: list[CharacterBrief] = Field(
        default_factory=list,
        description="恰好为指定数量的角色列表，不可多不可少",
    )

    @property
    def count(self) -> int:
        return len(self.characters)

    def validate_count(self, expected: int) -> bool:
        return self.count == expected


# === 提示词模板 ===

CLUES_SYSTEM = """你是一位资深剧本杀游戏设计师。根据提供的剧本终稿，设计恰好 {num_rounds} 轮线索发现阶段。

## 输出要求

生成 clue_stages 列表，恰好 {num_rounds} 个元素。每个元素包含两个文本字段：

1. clue_analysis_notice: 线索分析阶段的系统消息（含本轮发现的线索描述、分析引导）
2. free_discussion_notice: 自由讨论阶段的系统消息（引导玩家讨论的方向）

## 线索提取原则
- 严格按照剧本终稿内容提取线索，不要添加任何未在剧本中出现的信息
- 每轮线索应在200-400字
- 线索应逐步深入，前期线索较为模糊，后期线索指向性更强
- 必须从终稿的角色经历、时间线、物证中提取，不可凭空编造

## free_speech_limits
每轮自由讨论最大发言次数，值为1-3的小正整数，列表长度恰好 {num_rounds}。

## 参考输出格式（以3轮为例，实际必须根据终稿内容生成）

clue_stages:
  - clue_analysis_notice: |
      各位玩家，第一轮线索发现阶段开始。
      在案发现场的书桌抽屉中，发现了一封未署名的信件。信中写道：「你欠我的，该还了。下周之前，你应该知道后果。」
      字迹潦草，似乎是在匆忙中写下的。
      请各位仔细分析这条线索，思考：这封信可能是写给谁的？信中提到的「欠债」与案件有何关联？
  - free_discussion_notice: |
      第一轮线索分析结束。现在进入自由讨论阶段。
      请各位围绕刚才发现的信件展开讨论，可以分享自己的看法，也可以质疑其他人的陈述。
      注意：每个人都有不想被发现的秘密，请谨慎发言。

  - clue_analysis_notice: |
      第二轮线索发现。在花园的废弃工具棚中，发现了一把沾有泥土的铁铲和一件被刻意藏起的带血外套。
      铁铲上残留着新鲜泥土的痕迹，外套的口袋中有一张撕碎的照片碎片。
      请分析：这些物品分别属于谁？它们为何被藏在工具棚中？
  - free_discussion_notice: |
      第二轮线索分析结束，进入自由讨论。
      请围绕铁铲和外套展开讨论，尝试还原案发当晚各人的行踪。

  - clue_analysis_notice: |
      最后一轮线索发现。在死者的手机中发现了案发前一晚的一段录音。
      录音中可以听到死者与某人的争吵：「你明明答应过不会再提起那件事！」「你毁了我的人生，我绝不会放过你。」
      随后是一声重物落地的声音，录音戛然而止。
      这是最后的关键线索。请结合之前发现的所有线索，做出你的最终推理。
  - free_discussion_notice: |
      最后的自由讨论机会。请各位充分利用所有已发现的线索，进行最终推理和辩论。
      真相即将揭晓，请谨慎做出你的判断。

free_speech_limits: [2, 3, 2]"""

SCENES_SYSTEM = """你是一位资深剧本杀游戏设计师。根据提供的剧本终稿，生成游戏流程中的非线索场景消息。

## 输出要求

1. opening_notice: 游戏开场系统消息（800-1200字）
   - 营造悬疑氛围，介绍故事背景
   - 描述案发概况，引出主要人物
   - 设定游戏开始的紧张感

2. summary_notice: 总结发言阶段系统消息（100-200字）
   - 引导玩家进行最终总结和推理

3. vote_notice: 投票阶段系统消息（100-200字）
   - 引导玩家投票指认凶手

4. truth_reveal_notice: 真相揭晓系统消息（800-1500字）
   - 以主持人身份揭晓完整真相
   - 逐一揭示各角色的秘密和动机
   - 还原作案过程和时间线

## 多结局处理
如果剧本设计涉及多种结局（如不同凶手、不同真相），在 truth_reveal_notice 中应覆盖所有可能的结局分支。

5. full_truth: 完整真相文本（800-1500字）
   - 涵盖所有角色的真实动机和作案过程
   - 完整时间线还原"""

METADATA_SYSTEM = """你是一位剧本杀游戏内容编辑。根据提供的剧本信息，生成元数据。

要求：
1. overview: 剧本概述（100-200字），简洁干净，适合列表页展示，不要包含 markdown 格式
2. tags: 3-5个中文标签，逗号分隔，如：悬疑,古风,客栈,密室,情感
3. description: 剧本详细描述（300-500字），用于详情页面展示，包含故事背景、角色设定概要、游戏特色"""

CHARACTER_SYSTEM = """你是一位资深剧本杀编剧和角色设计师。请为指定角色生成完整的角色数据。

【关键约束】name 字段必须严格等于「{char_name}」，不得修改、替换或变体。例如角色名是「林墨」则 name 只能填「林墨」。

## 生成要求

### character_script（个人剧本，1500-3000字）
第一人称视角的完整剧本，包含：
- 身份与背景（200-300字）
- 与死者的关系和恩怨
- 案发当晚详细时间线（精确到分钟）
- 「重要提示」：该角色知道但不想让别人知道的关键信息
- 「支线任务」：游戏中需要完成的额外目标

原则：只包含该角色知道的信息；凶手剧本要隐藏作案细节但保留暗示

### profile（角色简介，100-200字）
用于游戏开始前角色选择时展示的模糊概述。不暴露核心秘密，只描述外在特征和身份

### appearance（外貌描述，100-200字）
用于AI绘图的提示词。包含：体型、发型发色、服装风格、显著特征

### system_prompt（AI系统提示词）
AI扮演该角色时使用的系统提示词，必须包含以下结构化部分：

【角色身份】姓名、性别、年龄、职业
【核心背景】该角色的关键经历（不包含具体时间线，agent可通过工具读取character_script获取细节）
【你的目标】隐藏秘密、分析线索、推理真凶、引导讨论
【需要保守的秘密】该角色最核心的秘密
【人际关系】与其他角色的关系和态度
【你掌握的关键信息】该角色独知的重要信息（概括性描述，不要照搬剧本原文）

### step_voice_id（TTS 音色选择）
为该角色在游戏中的实时语音选择最合适的音色 ID。根据角色的性别、年龄、性格特点选择。

可用音色列表：

男声（9个）：
- wenrounansheng：温柔男声，适合温和儒雅的男性角色
- wenrougongzi：温柔公子，适合年轻文雅的贵族或书生角色
- yuanqinansheng：元气男声，适合活力充沛的年轻男性
- cixingnansheng：磁性男声，适合成熟稳重或有魅力的男性
- zhengpaiqingnian：正派青年，适合正义感强的年轻男性
- qingniandaxuesheng：青年大学生，适合学生或知识分子角色
- boyinnansheng：播音男声，适合严肃正式的男性角色
- ruyananshi：儒雅男士，适合斯文有教养的男性
- shenchennanyin：深沉男音，适合神秘或老练的男性

女声（18个）：
- elegantgentle-female：优雅温柔女声，适合温婉知性的女性
- livelybreezy-female：活泼轻快女声，适合开朗外向的女性
- jingdiannvsheng：经典女声，适合普通年轻女性
- wenroushunv：温柔淑女，适合温柔贤淑的女性
- tianmeinvsheng：甜美女声，适合可爱甜美的女性
- qingchunshaonv：清纯少女，适合天真纯洁的少女
- yuanqishaonv：元气少女，适合活泼开朗的少女
- linjiajiejie：邻家姐姐，适合亲切友善的年轻女性
- qinqienvsheng：亲切女声，适合热情友善的女性
- wenrounvsheng：温柔女声，适合性格柔和的女性
- jilingshaonv：机灵少女，适合聪明伶俐的少女
- ruanmengnvsheng：软萌女声，适合娇小可爱的女性
- youyanvsheng：优雅女声，适合气质优雅的女性
- lengyanyujie：冷艳御姐，适合成熟冷艳的女性
- shuangkuaijiejie：爽快姐姐，适合直爽干练的女性
- wenjingxuejie：文静学姐，适合文静内敛的年轻女性
- linjiameimei：邻家妹妹，适合乖巧活泼的少女
- zhixingjiejie：知性姐姐，适合理性知性的女性

选择原则：
- 必须根据角色性别选择对应性别的音色
- 根据年龄、性格、职业等特征选择最贴切的音色
- 如果角色是老年女性，选择沉稳的音色；如果是少女，选择年轻清新的音色
- 只能填写上述列表中的一个 ID，不要填写列表外的值"""

DISCOVER_SYSTEM = (
    "你是一个数据提取专家。从剧本中精确提取所有可扮演角色的基本信息。\n"
    "【严格约束】你必须返回恰好为指定数量的角色，不可多、不可少。\n"
    "仔细通读全文，逐段检查每个角色，确保不遗漏任何一个可扮演角色。"
)


# === 辅助函数 ===


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
