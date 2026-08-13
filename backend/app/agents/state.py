"""
Agent状态定义
定义Agent的自定义状态字段，用于传递游戏上下文

GameAgentState 继承 LangChain 的 AgentState，添加游戏相关字段。

注意:
1. my_suspicion_graph 和 my_suspected_by 不在此处维护，
   它们通过 reaction_agent 维护到数据库，主 Agent 通过 get_my_game_state_info 工具从数据库读取。
2. db_session 不再包含在状态中，而是通过 contextvars 传递，避免序列化问题
"""

from langchain.agents import AgentState


class GameAgentState(AgentState):
    """
    游戏Agent状态

    继承自LangChain AgentState，添加游戏相关字段。
    这些字段在每次speak()调用时注入，供Tools和Middleware使用。

    游戏上下文 (由flow_controller注入):
    - session_id: 游戏会话ID
    - script_id: 剧本ID
    - character_id: 当前角色ID
    - character_name: 当前角色名称
    - current_stage: 当前游戏阶段
    - current_round: 当前轮次
    - character_name_map: ID到名称的映射
    - character_names: 当前剧本中所有角色名称列表（用于校验）

    注意: db_session 通过 contextvars 传递，不包含在可序列化的状态中
    """

    # ========================================
    # 游戏上下文 (由flow_controller注入)
    # ========================================
    session_id: str
    script_id: str
    character_id: str
    character_name: str
    current_stage: str
    current_round: int

    # ID到名称的映射 (用于工具中转换)
    character_name_map: dict[str, str]

    # 当前剧本中所有角色名称列表（用于校验）
    character_names: list[str]
