"""Validated model outputs and client commands for outline creation."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QuestionOption(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=100)
    impact: str = Field(min_length=1, max_length=300)


class OutlineQuestion(BaseModel):
    title: str = Field(
        min_length=1, max_length=80, description="独立引导标题，例如：您来确定剧情走向："
    )
    question: str = Field(min_length=1, max_length=400)
    options: list[QuestionOption] = Field(min_length=2, max_length=4)
    recommended_option_id: str

    @model_validator(mode="before")
    @classmethod
    def normalize_explicit_recommendation(cls, value):
        # Some providers express the same explicit recommendation on the option.
        # Normalize only an unambiguous choice; never invent a recommendation.
        if isinstance(value, dict) and not value.get("recommended_option_id"):
            recommended = [
                option.get("id")
                for option in value.get("options", [])
                if isinstance(option, dict) and option.get("recommended") is True
            ]
            if len(recommended) == 1 and recommended[0]:
                value = {**value, "recommended_option_id": recommended[0]}
        return value

    @model_validator(mode="after")
    def valid_options(self):
        ids = [item.id for item in self.options]
        if len(ids) != len(set(ids)) or self.recommended_option_id not in ids:
            raise ValueError("选项 ID 必须唯一且推荐选项必须存在")
        return self


class Direction(BaseModel):
    action: Literal["ask", "continue", "finalize"]
    next_task: str = Field(default="", max_length=1600)
    question: OutlineQuestion | None = None
    unresolved: list[str] = Field(default_factory=list, max_length=12)
    ai_decisions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def valid_action(self):
        if self.action == "ask" and self.question is None:
            raise ValueError("ask 必须返回完整问题")
        if self.action != "finalize" and not self.next_task.strip():
            raise ValueError("必须明确下一段写作任务")
        return self


class OutlineAction(BaseModel):
    action: Literal["answer", "pause", "continue", "stop_questions", "rewrite", "retry", "save"]
    request_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=1)
    question_id: str | None = None
    checkpoint_id: str | None = None
    option_id: str | None = None
    other_text: str = Field(default="", max_length=8000)
    content: str | None = Field(default=None, max_length=200000)

    @model_validator(mode="after")
    def valid_answer(self):
        if self.action == "save" and (self.content is None or not self.content.strip()):
            raise ValueError("大纲内容不能为空")
        if self.action in {"answer", "rewrite"}:
            if not self.question_id:
                raise ValueError("请选择要回答或修改的决策点")
            if not self.option_id and not self.other_text.strip():
                raise ValueError("请选择一个方向或输入其他想法")
        return self


def new_session() -> dict:
    return {
        "protocol_version": 2,
        "revision": 1,
        "status": "writing",
        "segments": [],
        "decisions": [],
        "pending_question": None,
        "unresolved": [],
        "questions_asked": 0,
        "automatic_segments": 0,
        "repairs": 0,
        "check": None,
        "consumed_requests": [],
        "next_action": "write",
        "next_task": "只写120–200字的背景与案件钩子。尚未在创意中明确的真凶、动机和核心反转不要提前写死。不要向用户提问，不要输出完整大纲。",
    }


class OutlineConflict(ValueError):
    pass
