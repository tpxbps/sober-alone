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

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Union

from langchain.messages import HumanMessage
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

from app.agents.agent_prompts import build_role_system_prompt
from app.agents.context import clear_db_session, set_db_session
from app.agents.game_model_paths import (
    bind_reaction_output,
    build_role_agent,
    create_game_model,
    visible_speech_text,
)
from app.agents.reaction import (
    REACTION_SLOW_LOG_SECONDS,
    HumanSpeechReactionPayload,
    SpeechReaction,
    SpeechReactionPayload,
    build_reaction_analysis_prompt,
    build_reaction_system_prompt,
)
from app.core.config import settings
from app.core.llm_factory import create_summary_llm

logger = logging.getLogger(__name__)


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
        rag_enabled: bool | None = None,
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
        self.rag_enabled = bool(settings.ZHIPUAI_API_KEY) if rag_enabled is None else rag_enabled

        # LLM配置
        self.llm_provider = llm_provider or settings.DEFAULT_LLM_PROVIDER
        self.llm_model = llm_model or settings.get_llm_model_name(self.llm_provider)

        # thread_id用于checkpointer
        self.thread_id = f"{session_id}_{character_id}"

        # 初始化Agent
        self._middleware = middleware or []
        self._checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self._agent: Any = None  # 主角色扮演Agent实例
        self._reaction_structured: Any = None  # 结构化输出 LLM（直接 with_structured_output）

        # 创建Agent
        self._create_agent()
        self._create_reaction_agent()

    def _init_model(self):
        """初始化LLM模型"""
        try:
            return create_game_model(
                self.llm_model, "speech", api_key=settings.get_api_key(self.llm_provider.lower())
            )
        except Exception:
            # 如果初始化失败，使用默认模型
            return create_game_model(settings.get_llm_model_name(), "speech")

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
        self._agent = build_role_agent(
            self._init_model(),
            self._init_summary_model(),
            system_prompt=self._build_system_prompt(),
            rag_enabled=self.rag_enabled,
            checkpointer=self._checkpointer,
            middleware=self._middleware,
        )

    def _create_reaction_agent(self):
        """
        创建用于反应分析的结构化输出 LLM。

        反应继续使用角色自己所选的模型，保持角色理解与可见发言一致。
        """
        self.reaction_llm_model = self.llm_model
        try:
            reaction_model = create_game_model(
                self.reaction_llm_model,
                "reaction",
                api_key=settings.get_api_key(self.llm_provider.lower()),
            )
        except Exception:
            reaction_model = self._init_model()

        # Reactions are typed inference results, not optional business-tool calls.
        # Use the provider-supported format; health probes share this registry
        # choice and the same Pydantic validation contract.
        self._human_reaction_structured = bind_reaction_output(
            reaction_model, self.reaction_llm_model, HumanSpeechReactionPayload
        )
        self._reaction_structured = bind_reaction_output(reaction_model, self.reaction_llm_model)
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
若需要调用该工具，必须先调用并等待结果，之后再输出完整的 Markdown 发言；不要先发言再调用工具。
""",
            "free_discussion": """
【当前阶段：自由讨论】
现在是自由讨论时间。
要求：
1. 主动回应他人的质疑，有针对性
2. 可以质疑其他玩家的发言，但要有理有据
3. 保持角色立场，不要暴露关键秘密
4. 只选一个最值得回应或推进的重点展开；其他次要观点简单提及即可
5. 禁止逐个点名点评所有玩家，尽量用精简的 2-4 个短段落完成发言
6. 如需回忆个人剧本，先完成检索工具调用，再输出一段完整的 Markdown 发言

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
            perspectives = (
                {}
                if game_state.get("observations_managed")
                else agent_state.get("my_player_perspectives", {})
            )
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
        human_speech_context = game_state.get(
            "observations_context", game_state.get("human_speech_context", "")
        )

        # 组合最终消息
        if stage_prompt:
            user_message = (
                f"{stage_prompt}\n\n{human_speech_context}\n\n{knowledge_context}\n\n{context}"
            )
        elif human_speech_context:
            user_message = f"{human_speech_context}\n\n{knowledge_context}\n\n{context}"
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
            "public_clues": game_state.get("public_clues", []),
            "personal_script": getattr(self, "personal_script", ""),
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

                    for text_content in visible_speech_text(token):
                        yield StreamToken(text=text_content, node=node)

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
        *,
        reaction_context: dict | None = None,
    ) -> SpeechReaction:
        """
        对其他玩家的发言做出反应，并结构化返回反应结果

        Args:
            speaker_name: 发言者名称
            content: 发言内容

        Returns:
            SpeechReaction: 结构化的反应结果
        """
        reaction_context = reaction_context or {}
        is_human = reaction_context.get("is_human", False)
        structured = self._human_reaction_structured if is_human else self._reaction_structured
        schema = HumanSpeechReactionPayload if is_human else SpeechReactionPayload
        if structured is not None:
            started_at = time.perf_counter()
            analysis_prompt = build_reaction_analysis_prompt(
                self.character_name,
                speaker_name,
                content,
                current_state=reaction_context.get("current_state"),
                public_clues=reaction_context.get("public_clues"),
                character_names=reaction_context.get("character_names"),
                is_human=is_human,
            )

            for attempt in range(2):
                prompt = analysis_prompt
                if attempt == 1:
                    prompt += """

【格式纠正】上次返回格式不符合要求。suspicion_changes 和
suspected_by_changes 必须是数组；没有变化时返回空数组。main_perspective 必须是字符串，
不要返回数组或对象；score 必须是 0 到 1 的绝对怀疑程度。请重新返回完整结构。"""
                if is_human:
                    prompt = prompt.replace("main_perspective 必须是字符串，", "")
                try:
                    result = await structured.ainvoke(
                        [
                            SystemMessage(
                                content=build_reaction_system_prompt(
                                    self.system_prompt, self.personal_script, is_human=True
                                )
                                if is_human
                                else self._reaction_system_prompt
                            ),
                            HumanMessage(content=prompt),
                        ]
                    )
                    reaction = None
                    if result and isinstance(result, schema):
                        reaction = result.to_reaction()
                    elif isinstance(result, dict):
                        reaction = schema.model_validate(result).to_reaction()
                    if reaction is not None:
                        allowed = set(reaction_context.get("character_names") or [])
                        targets = set(reaction.my_suspicion_graph) | set(reaction.my_suspected_by)
                        if (
                            allowed
                            and targets
                            and (targets - allowed or self.character_name in targets)
                        ):
                            raise ValueError("反应包含非法角色")
                        elapsed = time.perf_counter() - started_at
                        if elapsed >= REACTION_SLOW_LOG_SECONDS:
                            logger.info(
                                "Slow reaction analysis character=%s model=%s duration_ms=%d "
                                "attempt=%d",
                                self.character_id,
                                self.reaction_llm_model,
                                round(elapsed * 1000),
                                attempt + 1,
                            )
                        return reaction
                except (ValidationError, OutputParserException, ValueError) as exc:
                    if attempt == 0:
                        continue
                    logger.warning(
                        "Reaction schema repair failed character=%s model=%s error=%s",
                        self.character_id,
                        self.reaction_llm_model,
                        type(exc).__name__,
                    )
                except Exception as exc:
                    logger.warning(
                        "Reaction analysis failed character=%s model=%s error=%s "
                        "status=%s request_id=%s",
                        self.character_id,
                        self.reaction_llm_model,
                        type(exc).__name__,
                        getattr(exc, "status_code", None),
                        getattr(exc, "request_id", None),
                    )
                    break

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
