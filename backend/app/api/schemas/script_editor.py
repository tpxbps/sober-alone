from pydantic import BaseModel


class StartWorkflowRequest(BaseModel):
    user_idea: str
    player_count: int = 4
    difficulty: int = 1
    num_clue_rounds: int = 2
    prompts: dict | None = None


class ResumeWorkflowRequest(BaseModel):
    action: str
    content: str | None = None
    characters: list | None = None
    character_scripts: dict | None = None
    human_review: str | None = None
    game_data_sections: dict | None = None
    prompt: str | None = None


class UpdatePromptRequest(BaseModel):
    prompt: str


class UpdateTitleRequest(BaseModel):
    script_title: str


class ForkRequest(BaseModel):
    checkpoint_id: str
    state_updates: dict | None = None


class ChatRequest(BaseModel):
    message: str
    model: str = "deepseek-v4-flash"
    chat_session_id: str
    workflow_thread_id: str | None = None
