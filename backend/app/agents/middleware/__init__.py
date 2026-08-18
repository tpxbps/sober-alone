"""
Agent Middleware package
AI角色扮演智能体的中间件
"""

from app.agents.middleware.clean_history import clear_irrelevant_history_messages

__all__ = [
    "clear_irrelevant_history_messages",
]
