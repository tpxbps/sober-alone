"""
Agent context variables

用于在Agent工具之间共享非序列化的上下文信息（如数据库会话）
"""

from contextvars import ContextVar
from typing import Any

# 数据库会话上下文变量
# 用于在Agent工具中访问数据库，而不需要将其包含在可序列化的状态中
_db_session_context: ContextVar[Any | None] = ContextVar("db_session", default=None)


def set_db_session(db_session: Any) -> None:
    """设置当前上下文的数据库会话"""
    _db_session_context.set(db_session)


def get_db_session() -> Any | None:
    """获取当前上下文的数据库会话"""
    return _db_session_context.get()


def clear_db_session() -> None:
    """清除当前上下文的数据库会话"""
    _db_session_context.set(None)
