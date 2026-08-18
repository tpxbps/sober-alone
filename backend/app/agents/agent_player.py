"""
AgentPlayer - AI角色扮演智能体核心类
使用新版LangChain构建，支持剧本杀角色扮演

主要特性:
1. 使用 create_agent() 创建Agent，支持 state_schema
2. 使用 llm_factory 统一初始化LLM
3. 支持多种LLM提供商
4. 支持流式输出 (多种stream_mode)
5. 使用checkpointer持久化记忆
6. 支持LangChain中间件
7. 使用 structured output 进行反应分析
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Union, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRetryMiddleware,
    SummarizationMiddleware,
    ToolRetryMiddleware,
)
from langchain.messages import AIMessageChunk, HumanMessage
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.context import clear_db_session, set_db_session
from app.agents.reaction import SpeechReaction, build_reaction_system_prompt
from app.agents.state import GameAgentState
from app.core.config import settings
from app.core.llm_factory import SupportedModel, create_llm, create_summary_llm

# 瓶颈 step-3.5-flash: 256K
SUMMARY_TRIGGER_TOKENS = 200000


# ========================================
# Streaming Output Types
# ========================================


@dataclass
class StreamToken:
    """LLM文本token - 用于实时显示生成的文本"""

    type: str = "token"
    text: str = ""
    node: str = ""  # 来源节点 (model, tools, etc.)


@dataclass
class StreamProgress:
    """Agent进度更新 - 显示Agent当前状态（工具调用友好提示）"""

    type: str = "progress"
    step: str = ""  # model, tools, etc.
    status: str = ""  # 工具调用提示文案（如"正在回忆具体细节..."）


@dataclass
class StreamError:
    """Agent流式输出错误 - 区别于正常文本token"""

    type: str = "error"
    message: str = ""


# 流式输出的联合类型
StreamChunk = Union[StreamToken, StreamProgress, StreamError]


class AgentPlayer:
    """
    AI角色扮演智能体

    功能：
    1. 角色扮演：根据预设的system_prompt扮演剧本杀角色
    2. 记忆检索：通过RAG检索个人剧本细节
    3. 状态更新：维护和更新游戏心理状态
    4. 流式输出：支持流式生成对话内容

    使用LangChain构建，支持多种LLM提供商。

    使用方法：
    ```python
    agent = AgentPlayer(
        character_id="xxx",
        system_prompt="你是张三...",
        script_id="xxx",
        session_id="xxx",
        llm_provider="stepfun",
        llm_model="step-3.5-flash"
    )

    # 流式发言
    async for chunk in agent.speak(game_state, "intro"):
        print(chunk, end="")

    # 对其他玩家发言做出反应
    reaction = await agent.react_to_speech("李四", "我怀疑张三是凶手")
    ```
    """

    def __init__(
        self,
        character_id: str,
        system_prompt: str,
        script_id: str,
        session_id: str,
        character_name: str = "",
        personal_script: str = "",
        llm_provider: str | None = None,
        llm_model: str | None = None,
        middleware: list[Any] | None = None,
        checkpointer: Any | None = None,
    ):
        """
        初始化AgentPlayer

        Args:
            character_id: 角色ID
            system_prompt: 系统提示词（角色设定）
            script_id: 剧本ID
            session_id: 游戏会话ID
            character_name: 角色名称
            llm_provider: LLM提供商 (deepseek/...)
            llm_model: 具体模型名称，为None时使用默认值
            middleware: 额外的中间件列表
            checkpointer: LangGraph checkpointer实例，默认使用InMemorySaver
        """
        self.character_id = character_id
        self.character_name = character_name
        self.script_id = script_id
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.personal_script = personal_script
        self.rag_enabled = bool(settings.ZHIPUAI_API_KEY)

        # LLM配置
        self.llm_provider = llm_provider or settings.DEFAULT_LLM_PROVIDER
        self.llm_model = llm_model or settings.get_llm_model_name(self.llm_provider)

        # thread_id用于checkpointer
        self.thread_id = f"{session_id}_{character_id}"

        # 初始化Agent
        self._middleware = middleware or []
        self._checkpointer = checkpointer or InMemorySaver()
        self._agent: Any = None  # 主角色扮演Agent实例
        self._reaction_structured: Any = None  # 结构化输出 LLM（直接 with_structured_output）

        # 创建Agent
        self._create_agent()
        self._create_reaction_agent()

    def _init_model(self):
        """初始化LLM模型"""
        try:
            return create_llm(
                model=cast(SupportedModel, self.llm_model.lower()),
                temperature=0.8,
                api_key=settings.get_api_key(self.llm_provider.lower()),
                timeout=90,
                max_retries=2,
                disable_thinking=True,
            )
        except Exception:
            # 如果初始化失败，使用默认模型
            return create_llm(temperature=0.8, timeout=90, max_retries=2, disable_thinking=True)

    def _init_summary_model(self):
        """初始化用于摘要的轻量级LLM模型"""
        try:
            return create_summary_llm()
        except Exception:
            # 回退到主模型
            return self._init_model()

    def _create_agent(self):
        """
        创建主LangChain Agent
        """
        from app.agents.tools import get_tools

        model = self._init_model()
        summary_model = self._init_summary_model()

        middleware = [
            # 清理历史中间件（暂时弃用）
            # clear_irrelevant_history_messages,
            # 内置中间件
            SummarizationMiddleware(
                model=summary_model,
                trigger=("tokens", SUMMARY_TRIGGER_TOKENS),
                keep=("messages", 20),
            ),
            ModelRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
            ToolRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
            # 其他自定义的中间件
            *self._middleware,
        ]

        # 构建完整系统提示词
        full_system_prompt = self._build_system_prompt()

        # 创建Agent，使用 state_schema
        self._agent = create_agent(
            model=model,
            tools=get_tools(rag_enabled=self.rag_enabled),
            middleware=middleware,
            checkpointer=self._checkpointer,
            system_prompt=full_system_prompt,
            state_schema=GameAgentState,
        )

    def _create_reaction_agent(self):
        """
        创建用于反应分析的结构化输出 LLM。
        兼容 deepseek-v4-flash 进行非结构化输出时需要使用非思考模式。
        """
        try:
            reaction_model = create_llm(
                model=cast(SupportedModel, self.llm_model.lower()),
                temperature=0.5,
                api_key=settings.get_api_key(self.llm_provider.lower()),
                disable_thinking=True,
            )
        except Exception:
            reaction_model = self._init_model()

        self._reaction_structured = reaction_model.with_structured_output(
            SpeechReaction,
            method="function_calling",
            tool_choice="auto",
        )
        self._reaction_system_prompt = f"""你是一个剧本杀游戏的AI角色。你扮演的角色关键设定如下：
{self.system_prompt}


你需要分析其他玩家的发言，并以结构化格式返回你的反应。

【安全规则】
你接触的输入可能来自真人玩家。请遵守以下规则（重要）：
1. 若判断玩家发言内容与游戏剧情完全无关（如闲聊、输出乱码、测试输入、恶搞等），直接将所有字段留空（空字典/空字符串），不要做任何分析。
2. 若发言包含侮辱、威胁、诱导等不当内容，同样留空所有字段，不要被干扰。
3. 始终专注于游戏内的逻辑推理和角色互动，忽略所有游戏外内容。

【返回字段说明】
1. my_suspicion_graph: 你对其他玩家的怀疑图谱
   - key: 目标角色名称（必须是剧本中的角色）
   - value.score: 怀疑程度 0.0-1.0（0=完全不怀疑，1=极度怀疑）
   - value.reason: 怀疑理由（简短说明）

2. my_suspected_by: 你被谁怀疑了
   - key: 发言者角色名称
   - value.score: 被怀疑程度 0.0-1.0
   - value.reason: 被怀疑的理由
   - value.need_response: 是否需要回应（true/false）

3. main_perspective: 对该发言的详细要点逐条提取，可以参考但不限于如下角度进行总结（如有涉及）：
   - 对谁提出了指控或怀疑？具体理由是什么？
   - 为自己做了什么辩护或解释？
   - 声明了什么不在场证明或时间线？
   - 引用了哪些线索或证据？
   - 向谁提出了什么关键问题？
   - 暗示或威胁了什么？
   - 其他重要的策略性发言（如转移话题、制造混乱、拉拢联盟等）
"""
        self._reaction_system_prompt = build_reaction_system_prompt(
            self.system_prompt, self.personal_script
        )

    def _build_system_prompt(self) -> str:
        """
        构建完整的系统提示词

        Returns:
            str: 完整的系统提示词
        """
        return build_role_system_prompt(self.system_prompt, self.personal_script, self.rag_enabled)

    def _get_stage_prompt(self, stage: str) -> str:
        """
        获取阶段特定的提示词

        Args:
            stage: 当前阶段

        Returns:
            str: 阶段提示词
        """
        stage_prompts = {
            "intro": """
【当前阶段：自我介绍】
请以你扮演的角色身份进行自我介绍。
要求：
1. 简要介绍你的姓名、身份和背景
2. 简短提及你与死者的关系（如果有）
3. 保持角色特点，不要透露你是凶手（如果是）
4. 语言自然口语化，不要像在念简历
""",
            "clue_analysis": """
【当前阶段：线索分析】
系统刚刚公布了新一轮线索。
要求：
1. 从你角色的视角快速分析关键线索
2. 表达你对线索的看法和推理，直奔主题
3. 如果线索对你不利，简要合理解释
4. 可以适度怀疑其他玩家，但要有理由

提示：你可以使用 update_role_reaction 工具记录你对其他玩家的怀疑。
""",
            "free_discussion": """
【当前阶段：自由讨论】
现在是自由讨论时间。
要求：
1. 主动回应他人的质疑，有针对性
2. 可以质疑其他玩家的发言，但要有理有据
3. 保持角色立场，不要暴露关键秘密

注意：你的心理状态（你怀疑谁、谁怀疑了你）已在上下文中提供。
""",
            "summary": """
【当前阶段：总结发言】
请进行最终的总结发言。
要求：
1. 简要总结你的关键观察和推理
2. 明确指出你认为的凶手人选及核心理由
3. 为自己的清白做最后辩护
4. 发言要有说服力，但不要啰嗦

注意：你的心理状态（你怀疑谁、谁怀疑了你）已在上下文中提供。
""",
            "vote": """
【当前阶段：投票】
这是投票阶段。你必须且只能调用 submit_final_vote 工具来投票。

调用方式：
submit_final_vote(suspect_name="角色全名", reasoning="1-2句投票理由")

重要：
- suspect_name 必须是完整的角色名（不是ID）
- reasoning 简述为什么认为此人是凶手
- 不要调用其他工具（如 recall_personal_script_memory），直接投票
- 不要输出任何文字，只调用工具
""",
            "review": """
【当前阶段：复盘】
游戏已经结束，真相已经揭晓。
你可以发表对游戏的感想和评价。
""",
        }
        return stage_prompts.get(stage, "")

    async def _build_knowledge_context(self, game_state: dict[str, Any]) -> str:
        """
        构建玩家知识上下文，用于注入到发言提示词中

        包括:
        1. 怀疑图谱 - 我怀疑谁及理由
        2. 被怀疑记录 - 谁怀疑了我及理由
        3. 其他玩家发言要点 - 我对其他玩家发言的累计提炼

        Args:
            game_state: 游戏状态，需包含 db_session

        Returns:
            str: 格式化的知识上下文字符串
        """
        db_session = game_state.get("db_session")
        character_name_map = game_state.get("character_name_map", {})

        if not db_session:
            return ""

        try:
            from sqlalchemy import select

            from app.db.models import PlayerState

            # 获取当前玩家的状态
            result = await db_session.execute(
                select(PlayerState).where(
                    PlayerState.session_id == self.session_id,
                    PlayerState.character_id == self.character_id,
                )
            )
            player_state = result.scalar_one_or_none()

            if not player_state:
                return ""

            # 使用 PlayerState 的 get_agent_state 方法获取转换后的数据
            agent_state = player_state.get_agent_state(character_name_map)

            parts = []

            # 1. 怀疑图谱
            suspicion_graph = agent_state.get("my_suspicion_graph", {})
            if suspicion_graph:
                suspicion_lines = []
                for target_name, data in suspicion_graph.items():
                    score = data.get("score", 0)
                    reason = data.get("reason", "")
                    suspicion_lines.append(f"  - {target_name}: 怀疑度 {score:.1f}，理由: {reason}")
                parts.append("【我怀疑的人】\n" + "\n".join(suspicion_lines))

            # 2. 被怀疑记录
            suspected_by = agent_state.get("my_suspected_by", {})
            if suspected_by:
                suspected_lines = []
                for source_name, data in suspected_by.items():
                    score = data.get("score", 0)
                    reason = data.get("reason", "")
                    need_response = data.get("need_response", False)
                    response_hint = " (需要回应)" if need_response else ""
                    suspected_lines.append(
                        f"  - {source_name}: 怀疑度 {score:.1f}{response_hint}，理由: {reason}"
                    )
                parts.append("【怀疑我的人】\n" + "\n".join(suspected_lines))

            # 3. 其他玩家发言要点
            perspectives = agent_state.get("my_player_perspectives", {})
            if perspectives:
                perspective_lines = []
                for speaker_name, perspective in perspectives.items():
                    if perspective:
                        perspective_lines.append(f"  - {speaker_name}: {perspective}\n")
                if perspective_lines:
                    parts.append("【其他玩家发言要点】\n" + "\n".join(perspective_lines))

            if parts:
                return "【你的心理状态记录】\n" + "\n\n".join(parts)
            else:
                return ""

        except Exception as e:
            print(f"Error building knowledge context: {e}")
            return ""

    async def speak(self, game_state: dict[str, Any], stage: str) -> AsyncIterator[StreamChunk]:
        """
        推送系统消息，让AI角色发言(流式输出)

        使用 stream_mode=["messages", "custom"]:
        - messages: LLM最终回复的文本token
        - custom: 工具调用时的友好提示文案（由工具内部通过 get_stream_writer 发送）

        Args:
            game_state: 游戏状态 (包含 session_id, script_id, character_id, character_name,
                                  current_stage, current_round, db_session,
                                  character_name_map, character_names, context)
            stage: 当前阶段

        Yields:
            StreamChunk: 结构化的流式输出，可能是:
                - StreamToken: LLM生成的文本片段（仅最终发言内容）
                - StreamProgress: 工具调用进度提示（来自custom stream）
        """
        if self._agent is None:
            yield StreamToken(text="", node="error")
            return

        # 构建当前阶段系统推送消息
        context = game_state.get("context", "")
        stage_prompt = self._get_stage_prompt(stage)

        # 构建玩家知识上下文（怀疑图谱、被怀疑记录、 其他玩家发言要点）
        knowledge_context = await self._build_knowledge_context(game_state)

        # 组合最终消息
        if stage_prompt:
            user_message = f"{stage_prompt}\n\n{knowledge_context}\n\n{context}"
        elif knowledge_context:
            user_message = f"{knowledge_context}\n\n{context}"
        else:
            user_message = context

        # 基于自定义GameAgentState构架输入状态
        # 注意: db_session 通过 contextvars 传递，不包含在可序列化的状态中
        input_state = {
            "messages": [HumanMessage(content=user_message)],
            "session_id": game_state.get("session_id", self.session_id),
            "script_id": game_state.get("script_id", self.script_id),
            "character_id": game_state.get("character_id", self.character_id),
            "character_name": game_state.get("character_name", self.character_name),
            "current_stage": game_state.get("current_stage", stage),
            "current_round": game_state.get("current_round", 0),
            "character_name_map": game_state.get("character_name_map", {}),
            "character_names": game_state.get("character_names", []),
        }

        # 设置 db_session 到 contextvars (用于工具访问，不会被序列化)
        db_session = game_state.get("db_session")
        set_db_session(db_session)

        # 配置记忆持久化的 thread_id
        config = {"configurable": {"thread_id": self.thread_id}}

        # 使用 messages + custom stream mode
        # messages: 返回LLM的文本token
        # custom: 工具内部通过 get_stream_writer 发送的友好提示
        try:
            async for chunk in self._agent.astream(
                input_state, config, stream_mode=["messages", "custom"]
            ):
                # chunk 格式: (stream_mode, data)
                stream_mode, data = chunk

                if stream_mode == "messages":
                    # 处理LLM消息流
                    token, metadata = data
                    node = metadata.get("langgraph_node", "unknown") or "unknown"

                    if isinstance(token, AIMessageChunk):
                        # 跳过工具调用相关的chunk
                        if token.tool_calls or token.tool_call_chunks:
                            continue

                        # 处理 content_blocks - 只提取 text 类型的内容
                        if hasattr(token, "content_blocks") and token.content_blocks:
                            text_blocks = [
                                b for b in token.content_blocks if b.get("type") == "text"
                            ]
                            for block in text_blocks:
                                text_content = block.get("text", "")
                                if text_content:
                                    yield StreamToken(text=text_content, node=node)
                        # 回退：如果没有 content_blocks，使用 token.text
                        elif token.text:
                            yield StreamToken(text=token.text, node=node)

                elif stream_mode == "custom":
                    # 处理工具自定义消息 - 友好提示文案
                    async for result in self._process_custom_stream(data):
                        yield result

        except Exception as e:
            print(f"Error in stream: {e}")
            yield StreamError(message=str(e))
        finally:
            # 清除 db_session 上下文
            clear_db_session()

    async def _process_custom_stream(self, data: Any) -> AsyncIterator[StreamChunk]:
        """
        处理 custom stream mode 的输出

        工具内部通过 get_stream_writer 发送的友好提示

        Args:
            data: 自定义数据（字符串或字典）

        Yields:
            StreamChunk: StreamProgress（工具调用进度提示）
        """
        # data 可能是字符串或字典
        if isinstance(data, str):
            # 字符串格式的提示文案
            yield StreamProgress(step="tool", status=data)
        elif isinstance(data, dict):
            # 字典格式
            message = data.get("message", data.get("status", ""))
            step = data.get("step", "tool")
            yield StreamProgress(step=step, status=message)

    async def react_to_speech(
        self,
        speaker_name: str,
        content: str,
    ) -> SpeechReaction:
        """
        对其他玩家的发言做出反应，并结构化返回反应结果

        Args:
            speaker_name: 发言者名称
            content: 发言内容

        Returns:
            SpeechReaction: 结构化的反应结果
        """
        if self._reaction_structured is not None:
            analysis_prompt = f"""你是角色「{self.character_name}」。

请仔细分析以下发言：

发言者：{speaker_name}
发言内容：{content}

【任务】
1. 提炼该发言的所有关键要点（main_perspective）：
可以逐条梳理并且按编号列出（如"1.指控XX因为... 2.辩称自己... 3.不在场证明：..."）；
可以从以下方面进行思考（如有涉及）：
    - 对谁提出了指控或怀疑？具体理由是什么？
    - 为自己做了什么辩护或解释？
    - 声明了什么不在场证明或时间线？
    - 引用了哪些线索或证据？
    - 向谁提出了什么关键问题？
    - 其他重要的策略性发言
2. 如果该发言影响了你对其他玩家的怀疑程度，更新 my_suspicion_graph
3. 如果该发言在怀疑或攻击你，更新 my_suspected_by"""

            try:
                result = await self._reaction_structured.ainvoke(
                    [
                        SystemMessage(content=self._reaction_system_prompt),
                        HumanMessage(content=analysis_prompt),
                    ]
                )
                if result and isinstance(result, SpeechReaction):
                    return result
                elif isinstance(result, dict):
                    return SpeechReaction(**result)
            except Exception as e:
                print(f"Error analyzing speech with structured output: {e}")

        return SpeechReaction(
            my_suspicion_graph={},
            my_suspected_by={},
            main_perspective="",
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "script_id": self.script_id,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
        }
