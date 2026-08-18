"""
Agents module
AI角色扮演智能体
使用新版LangChain构建

主要组件:
- AgentPlayer: AI角色扮演核心类，使用create_agent()创建
- AgentManager: 多Agent管理器
- GameAgentState: Agent状态定义，继承自AgentState
- SpeechReaction: 反应分析结构化输出
- Tools: Agent工具集
- Middleware: Agent中间件
"""

from app.agents.agent_manager import (
    AgentInfo,
    AgentManager,
    get_agent_manager,
    remove_agent_manager,
)
from app.agents.agent_player import AgentPlayer, SpeechReaction
from app.agents.state import GameAgentState

__all__ = [
    "AgentPlayer",
    "SpeechReaction",
    "GameAgentState",
    "AgentManager",
    "AgentInfo",
    "get_agent_manager",
    "remove_agent_manager",
]
