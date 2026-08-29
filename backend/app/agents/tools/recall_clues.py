"""Tool for recalling only clues already public in the current game session."""

from langchain.tools import ToolRuntime, tool
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.context import get_db_session
from app.db.models import GameSession


class RecallCluesInput(BaseModel):
    clue_ids: list[str] = Field(
        default_factory=list,
        description="需要核对的公开线索 ID；留空时返回全部已公开线索",
    )
    query: str = Field(default="", description="可选的摘要或详情关键词")


@tool(args_schema=RecallCluesInput)
async def recall_public_clues(
    clue_ids: list[str],
    query: str,
    runtime: ToolRuntime,
) -> str:
    """Recall public system clues without exposing later stages."""

    get_stream_writer()("正在核对已公开线索...")
    db_session = get_db_session()
    session_id = runtime.state.get("session_id", "")
    if db_session is None or not session_id:
        return "当前无法读取公开线索。"
    result = await db_session.execute(
        select(GameSession).where(GameSession.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        return "游戏会话不存在。"

    requested = {item.lower() for item in (clue_ids or [])}
    needle = query.strip().lower()
    matches = []
    for clue in session.revealed_clues or []:
        clue_id = str(clue.get("id", "")).lower()
        haystack = f"{clue.get('summary', '')} {clue.get('content', '')}".lower()
        if requested and clue_id not in requested:
            continue
        if needle and needle not in haystack:
            continue
        matches.append(clue)
    if not matches:
        return "没有找到符合条件的已公开线索。"
    return "\n\n".join(
        f"[{clue.get('id')}] {clue.get('summary', '')}\n{clue.get('content', '')}"
        for clue in matches
    )
