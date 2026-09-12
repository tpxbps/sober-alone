from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class StartWorkflowRequest(BaseModel):
    user_idea: str
    player_count: int = 4
    difficulty: int = 1
    num_clue_rounds: int = 2
    ending_mode: Literal["single", "multiple"] = Field(
        default="single",
        deprecated=True,
        description="兼容旧客户端；新建创作固定使用单结局，多结局在结构化数据阶段手动配置。",
    )
    prompts: dict | None = None


class LegacyOwnershipClaimRequest(BaseModel):
    legacy_owner_uuids: list[UUID] = Field(min_length=1, max_length=100)


class ResumeWorkflowRequest(BaseModel):
    action: str
    content: str | None = None
    characters: list | None = None
    character_scripts: dict | None = None
    human_review: str | None = None
    quality_report_id: str | None = None
    game_data_sections: dict | None = None
    prompt: str | None = None
    selected_asset_ids: list[str] | None = None


class UpdatePromptRequest(BaseModel):
    prompt: str


class UpdateTitleRequest(BaseModel):
    script_title: str


class ForkRequest(BaseModel):
    checkpoint_id: str
    state_updates: dict | None = None


class ChatRequest(BaseModel):
    message: str
    model: str = "deepseek-flash"
    chat_session_id: str
    workflow_thread_id: str | None = None
