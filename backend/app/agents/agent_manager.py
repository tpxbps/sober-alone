"""
AgentManager - 多Agent管理器
管理游戏中所有AI角色的Agent实例
"""

import asyncio
from dataclasses import dataclass
from typing import Any, cast

from app.agents.agent_player import AgentPlayer
from app.core.config import settings


@dataclass
class AgentInfo:
    """Agent信息"""

    character_id: str
    character_name: str
    agent: AgentPlayer | None
    is_human: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None


class AgentManager:
    """
    多Agent管理器

    职责：
    1. 创建和管理所有AI角色的Agent实例
    2. 维护角色ID与Agent实例的映射
    3. 支持为每个角色选择不同的LLM
    4. 批量操作（如批量反应更新）
    5. Agent实例的生命周期管理
    """

    def __init__(self, session_id: str, script_id: str):
        """
        初始化AgentManager

        Args:
            session_id: 游戏会话ID
            script_id: 剧本ID
        """
        self.session_id = session_id
        self.script_id = script_id
        self.agents: dict[str, AgentInfo] = {}
        self.human_character_id: str | None = None

    async def initialize_agents(
        self,
        characters: list[dict[str, Any]],
        human_character_id: str,
        llm_configs: dict[str, dict[str, str | None]] | None = None,
    ) -> dict[str, AgentPlayer]:
        """
        初始化所有Agent

        Args:
            characters: 角色信息列表，包含character_id, name, system_prompt等
            human_character_id: 真人玩家选择的角色ID
            llm_configs: 可选的LLM配置，格式为 {character_id: {"provider": "stepfun", "model": "step-3.5-flash"}}

        Returns:
            Dict[str, AgentPlayer]: 角色ID到Agent实例的映射
        """
        self.human_character_id = human_character_id
        llm_configs = llm_configs or {}

        for char in characters:
            character_id = char.get("character_id")
            if not character_id:
                continue  # 跳过没有character_id的角色

            character_name = char.get("name", "")
            system_prompt = char.get("system_prompt", "")
            is_human = character_id == human_character_id

            # 获取该角色的LLM配置
            char_llm_config = llm_configs.get(character_id, {})
            llm_provider = char_llm_config.get("provider", settings.DEFAULT_LLM_PROVIDER)
            llm_model = char_llm_config.get("model")
            if not llm_provider or not settings.get_api_key(llm_provider):
                llm_provider = settings.DEFAULT_LLM_PROVIDER
                llm_model = settings.get_llm_model_name(llm_provider)

            if not is_human:
                # 创建AI Agent
                agent = AgentPlayer(
                    character_id=character_id,
                    system_prompt=system_prompt,
                    script_id=self.script_id,
                    session_id=self.session_id,
                    character_name=character_name,
                    personal_script=char.get("character_script", ""),
                    llm_provider=llm_provider,
                    llm_model=llm_model,
                )

                self.agents[character_id] = AgentInfo(
                    character_id=character_id,
                    character_name=character_name,
                    agent=agent,
                    is_human=False,
                    llm_provider=llm_provider,
                    llm_model=llm_model or settings.get_llm_model_name(llm_provider),
                )
            else:
                # 真人玩家，不创建Agent
                self.agents[character_id] = AgentInfo(
                    character_id=character_id,
                    character_name=character_name,
                    agent=None,
                    is_human=True,
                    llm_provider=None,
                    llm_model=None,
                )

        return {cid: info.agent for cid, info in self.agents.items() if info.agent}

    def get_agent(self, character_id: str) -> AgentPlayer | None:
        """
        获取指定角色的Agent实例

        Args:
            character_id: 角色ID

        Returns:
            Optional[AgentPlayer]: Agent实例，如果是真人玩家则返回None
        """
        info = self.agents.get(character_id)
        if info and not info.is_human:
            return info.agent
        return None

    def get_all_ai_agents(self) -> list[AgentPlayer]:
        """
        获取所有AI Agent实例

        Returns:
            List[AgentPlayer]: AI Agent列表
        """
        return [info.agent for info in self.agents.values() if info.agent]

    def get_character_name(self, character_id: str | None) -> str:
        """
        获取角色名称

        Args:
            character_id: 角色ID

        Returns:
            str: 角色名称
        """
        info = self.agents.get(character_id or "")
        return info.character_name if info else "未知"

    def is_human(self, character_id: str) -> bool:
        """
        判断是否是真人玩家

        Args:
            character_id: 角色ID

        Returns:
            bool: 是否是真人玩家
        """
        info = self.agents.get(character_id)
        return info.is_human if info else False

    def get_llm_info(self, character_id: str) -> dict[str, str | None]:
        """
        获取角色的LLM配置信息

        Args:
            character_id: 角色ID

        Returns:
            Dict: LLM配置信息 {"provider": str, "model": str}
        """
        info = self.agents.get(character_id)
        if info:
            return {"provider": info.llm_provider, "model": info.llm_model}
        return {"provider": None, "model": None}

    async def broadcast_speech(
        self,
        speaker_id: str,
        content: str,
    ) -> dict[str, Any]:
        """
        广播发言给所有其他AI Agent

        让其他AI Agent对发言做出反应（更新心理状态）

        Args:
            speaker_id: 发言者ID
            content: 发言内容

        Returns:
            Dict[str, Any]: 各Agent的反应结果
        """
        speaker_name = self.get_character_name(speaker_id)
        reactions = {}

        # 收集需要反应的agent
        agent_tasks = []
        agent_ids = []
        for char_id, info in self.agents.items():
            if char_id != speaker_id and info.agent:
                agent_ids.append(char_id)
                agent_tasks.append(
                    self._get_reaction_with_timeout(char_id, info.agent, speaker_name, content)
                )

        if agent_tasks:
            # 使用wait_for给每个任务添加超时，并收集结果
            results = await asyncio.gather(*agent_tasks, return_exceptions=True)

            for i, char_id in enumerate(agent_ids):
                result = results[i]
                if isinstance(result, Exception):
                    reactions[char_id] = {"error": str(result)}
                elif isinstance(result, dict) and "error" in result:
                    reactions[char_id] = result
                else:
                    reactions[char_id] = result

        return reactions

    async def _get_reaction_with_timeout(
        self,
        char_id: str,
        agent: AgentPlayer,
        speaker_name: str,
        content: str,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """
        带超时的获取单个Agent的反应

        Args:
            char_id: 角色ID
            agent: AgentPlayer实例
            speaker_name: 发言者名称
            content: 发言内容
            timeout: 超时时间（秒）

        Returns:
            Dict: 反应结果或错误信息
        """
        try:
            result = await asyncio.wait_for(
                agent.react_to_speech(speaker_name, content),
                timeout=timeout,
            )
            # 将 SpeechReaction 转换为 dict
            if hasattr(result, "model_dump"):
                return cast(dict[str, Any], result.model_dump())
            elif hasattr(result, "dict"):
                return cast(dict[str, Any], result.dict())
            elif isinstance(result, dict):
                return result
            else:
                # 最后的兜底：尝试转换为dict
                return cast(dict[str, Any], dict(result))
        except TimeoutError:
            return {"error": f"Reaction timed out after {timeout}s"}
        except Exception as e:
            return {"error": str(e)}

    async def make_ai_speak(self, character_id: str, game_state: dict[str, Any], stage: str):
        """
        让指定AI角色发言

        返回结构化的流式数据(StreamChunk)，包含:
        - StreamToken: LLM生成的文本片段
        - StreamToolCall: 工具调用
        - StreamToolResult: 工具执行结果
        - StreamProgress: Agent进度更新

        Args:
            character_id: 角色ID
            game_state: 游戏状态（包含 GameAgentState 所需的所有字段）
            stage: 当前阶段

        Yields:
            StreamChunk: 结构化的流式数据
        """
        agent = self.get_agent(character_id)
        if agent:
            async for chunk in agent.speak(game_state, stage):
                yield chunk

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "session_id": self.session_id,
            "script_id": self.script_id,
            "agents": {
                cid: {
                    "character_id": info.character_id,
                    "character_name": info.character_name,
                    "is_human": info.is_human,
                    "llm_provider": info.llm_provider,
                    "llm_model": info.llm_model,
                }
                for cid, info in self.agents.items()
            },
            "human_character_id": self.human_character_id,
        }


# 全局Agent管理器缓存
_agent_managers: dict[str, AgentManager] = {}


def get_agent_manager(session_id: str, script_id: str | None = None) -> AgentManager:
    """
    获取或创建Agent管理器

    Args:
        session_id: 游戏会话ID
        script_id: 剧本ID（创建新管理器时需要）

    Returns:
        AgentManager: Agent管理器实例
    """
    if session_id not in _agent_managers:
        if not script_id:
            raise ValueError("script_id is required when creating new AgentManager")
        _agent_managers[session_id] = AgentManager(session_id, script_id)
    return _agent_managers[session_id]


def remove_agent_manager(session_id: str):
    """
    移除Agent管理器（游戏结束时调用）

    Args:
        session_id: 游戏会话ID
    """
    if session_id in _agent_managers:
        del _agent_managers[session_id]
