"""Structured output contracts for script conversion."""

from pydantic import BaseModel, Field


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
