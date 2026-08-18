"""
Chat Service — AI 助手聊天服务
使用 create_agent + init_chat_model + checkpointer 实现自动历史管理
通过 tools 选择性披露工作流上下文，避免历史消息冗余
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRetryMiddleware,
    SummarizationMiddleware,
)
from langchain.messages import AIMessageChunk
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_config, get_stream_writer

from app.core.llm_factory import (
    create_chat_model_for_agent,
    create_summary_llm,
)
from app.script_editor.state import STEP_LABELS

logger = logging.getLogger(__name__)

CHAT_SYSTEM_PROMPT = """\
你是一位专业的剧本杀创作助手，正在帮助用户创作一份剧本杀游戏剧本。

你可以帮助用户：
- 构思故事情节和角色设定
- 梳理时间线和逻辑关系
- 设计线索和悬疑元素
- 润色文字和改善叙事
- 解答创作过程中的问题

## 工作流阶段

剧本创作分为以下阶段，按顺序推进：
1. **构思大纲** — 输入创意，AI生成大纲
2. **大纲审阅** — 审阅并修改大纲
3. **初稿创作** — 基于大纲撰写初稿并审阅
4. **审稿修订** — AI审稿 + 人类审稿 + 生成终稿
5. **终稿定稿** — 结构化数据转化与审阅
6. **资源生成** — 生成图片、语音等（自动）

## 重要：上下文与工具使用规则

- 系统会在每条用户消息前自动注入「当前进度」信息，这是系统自动生成的，不是用户提供的
- 回答时不要说"根据你提供的信息"之类的话，应该说"根据当前工作流的进度"
- 工具可以查看**当前正在进行阶段及之前所有阶段**已生成的内容（包括正在生成中的数据）
- **不要调用**尚未到达阶段的查看工具（会返回"尚未生成"）
- 只有用户明确要求查看已有内容时，才调用查看工具
- 用户只是在讨论创作思路时，不需要调用工具

## 工具查询策略

当需要查看多个阶段的内容时，应**从当前阶段向后查询**：
- 先调用当前阶段的查看工具
- 如果当前阶段尚未生成，再向前查询上一阶段
- 避免同时并行调用多个查看工具，减少上下文占用
- 每次最多调用 1-2 个工具即可，不要一次调用所有工具

## 重要：工具调用后必须回复

- 调用工具获取信息后，**必须**用自然语言向用户总结和回复
- 不要在调用工具后直接结束，用户需要看到你的分析和建议
- 如果工具返回"尚未生成"，请告知用户当前阶段状态，并建议等待

请用中文回复，保持专业但友好的语气。你的建议应该具体、可操作。
"""

# === 工作流状态存储（按会话 ID） ===

_workflow_states: dict[str, dict] = {}


def _set_workflow_state(session_id: str, state: dict):
    _workflow_states[session_id] = state


def _get_workflow_state() -> dict:
    """工具内部调用：获取当前会话的工作流状态"""
    config = get_config()
    session_id = config.get("configurable", {}).get("thread_id", "")
    return _workflow_states.get(session_id, {})


# === 工作流阶段顺序 ===
_STEP_ORDER = [
    "init",
    "generate_outline",
    "review_outline",
    "generate_first_draft",
    "review_first_draft",
    "review_by_llm",
    "generate_final_draft",
    "review_final",
    "convert_to_game_data",
    "review_game_data",
    "save_to_database",
    "generate_assets",
]


def _step_index(state: dict) -> int:
    """获取当前步骤在流程中的位置，-1 表示未开始"""
    step = state.get("current_step", "")
    if not step or step == "init":
        return -1
    try:
        return _STEP_ORDER.index(step)
    except ValueError:
        return -1


# === 工具定义 ===


@tool
def get_script_outline() -> str:
    """获取当前剧本大纲。仅在大纲审阅阶段及之后可用。"""
    writer = get_stream_writer()
    writer("正在查看剧本大纲...")
    state = _get_workflow_state()
    if _step_index(state) < _STEP_ORDER.index("review_outline"):
        return "当前尚未进入大纲审阅阶段，大纲还未生成。请先完成创意提交。"
    outline = state.get("outline", "")
    if not outline:
        return "大纲尚未生成完成。"
    return outline[:3000]


@tool
def get_script_characters() -> str:
    """获取当前角色列表及设定。仅在大纲审阅阶段及之后可用。"""
    writer = get_stream_writer()
    writer("正在查看角色设定...")
    state = _get_workflow_state()
    if _step_index(state) < _STEP_ORDER.index("review_outline"):
        return "当前尚未进入大纲审阅阶段，角色还未生成。"
    chars = state.get("characters", [])
    if not chars:
        return "角色列表尚未生成。"
    lines = []
    for c in chars:
        line = f"- {c.get('name', '?')}: {c.get('gender', '')}, {c.get('age', '')}岁, {c.get('occupation', '')}"
        if c.get("profile"):
            line += f"\n  简介: {c['profile'][:200]}"
        lines.append(line)
    return "\n".join(lines)


@tool
def get_script_first_draft() -> str:
    """获取当前剧本初稿。仅在初稿审阅阶段及之后可用。"""
    writer = get_stream_writer()
    writer("正在查看剧本初稿...")
    state = _get_workflow_state()
    if _step_index(state) < _STEP_ORDER.index("review_first_draft"):
        return "当前尚未进入初稿审阅阶段，初稿还未生成。"
    draft = state.get("first_draft", "")
    if not draft:
        return "初稿尚未生成完成。"
    return draft[:3000]


@tool
def get_script_review_opinion() -> str:
    """获取AI审稿意见。仅在审稿修订阶段及之后可用。"""
    writer = get_stream_writer()
    writer("正在查看审稿意见...")
    state = _get_workflow_state()
    if _step_index(state) < _STEP_ORDER.index("review_final"):
        return "当前尚未进入审稿修订阶段，审稿意见还未生成。"
    review = state.get("review_opinion", "")
    if not review:
        return "审稿意见尚未生成。"
    return review[:2000]


@tool
def get_script_final_draft() -> str:
    """获取终稿内容。仅在审稿修订阶段及之后可用。"""
    writer = get_stream_writer()
    writer("正在查看终稿...")
    state = _get_workflow_state()
    if _step_index(state) < _STEP_ORDER.index("review_final"):
        return "当前尚未进入审稿修订阶段，终稿还未生成。"
    draft = state.get("final_draft", "")
    if not draft:
        return "终稿尚未生成完成。"
    return draft[:3000]


@tool
def get_game_data_overview() -> str:
    """获取结构化游戏数据概览（角色列表、游戏流程、开场消息等）。仅在终稿定稿阶段及之后可用。"""
    writer = get_stream_writer()
    writer("正在查看游戏数据...")
    state = _get_workflow_state()
    if _step_index(state) < _STEP_ORDER.index("convert_to_game_data"):
        return "当前尚未进入终稿定稿阶段，游戏数据还未生成。"
    gds = state.get("game_data_sections", {})
    if not gds:
        return "游戏数据尚未生成完成。"
    parts = []
    if gds.get("overview"):
        parts.append(f"【概述】{gds['overview']}")
    if gds.get("opening"):
        parts.append(f"【开场消息】{gds['opening'][:500]}")
    char_data = gds.get("character_data", [])
    if char_data:
        chars = []
        for cd in char_data:
            name = cd.get("name", "?")
            gender = cd.get("gender", "")
            age = cd.get("age", "")
            occ = cd.get("occupation", "")
            chars.append(f"  - {name}: {gender}, {age}岁, {occ}")
        parts.append(f"【角色列表】({len(char_data)}人)\n" + "\n".join(chars))
    game_flow = gds.get("game_flow", [])
    if game_flow:
        flow = []
        for i, stage in enumerate(game_flow):
            t = stage.get("type", "?")
            title = stage.get("stage_title", t)
            flow.append(f"  {i + 1}. {title} ({t})")
        parts.append(f"【游戏流程】({len(game_flow)}个阶段)\n" + "\n".join(flow))
    if gds.get("truth_reveal"):
        parts.append(f"【真相揭晓】{gds['truth_reveal'][:500]}")
    return "\n\n".join(parts)[:3000]


CHAT_TOOLS = [
    get_script_outline,
    get_script_characters,
    get_script_first_draft,
    get_script_review_opinion,
    get_script_final_draft,
    get_game_data_overview,
]


def _build_step_hint(state: dict) -> str:
    """构建进度提示（注入用户消息中，告知当前阶段和可用内容）"""
    step = state.get("current_step", "")
    if not step or step == "init":
        return "[当前进度：尚未开始 — 用户正在构思创意，还没有生成任何内容]"

    label = STEP_LABELS.get(step, step)
    idx = _step_index(state)

    # 根据进度列出已可查看的内容
    available = []
    if idx >= _STEP_ORDER.index("review_outline"):
        available.append("大纲")
    if idx >= _STEP_ORDER.index("review_first_draft"):
        available.append("初稿")
    if idx >= _STEP_ORDER.index("review_final"):
        available.append("审稿意见")
        available.append("终稿")
    if idx >= _STEP_ORDER.index("convert_to_game_data"):
        available.append("游戏数据")

    available_str = "、".join(available) if available else "暂无"
    return f"[当前进度：{label}。已生成可查看的内容：{available_str}。请勿调用尚未到达阶段的工具。]"


# === 创建 chat agent（按 model 懒加载，每个 model 独立 checkpointer） ===

_chat_agents: dict[str, Any] = {}


def _get_chat_agent(model: str):
    """获取指定 model 的 chat agent 实例（懒加载）"""
    if model not in _chat_agents:
        llm = create_chat_model_for_agent(model)

        _chat_agents[model] = create_agent(
            model=llm,  # type: ignore[arg-type]
            tools=CHAT_TOOLS,
            middleware=[
                ModelRetryMiddleware(
                    max_retries=3,
                    backoff_factor=2.0,
                    initial_delay=1.0,
                ),
                SummarizationMiddleware(
                    model=create_summary_llm(),
                    trigger=("tokens", 200000),
                    keep=("messages", 20),
                ),
            ],
            checkpointer=InMemorySaver(),
            system_prompt=CHAT_SYSTEM_PROMPT,
        )
    return _chat_agents[model]


async def stream_chat_response(
    message: str,
    model: str = "deepseek-v4-flash",
    chat_session_id: str = "default",
    workflow_state: dict | None = None,
) -> AsyncGenerator[str]:
    """
    流式生成聊天回复（使用 create_agent + checkpointer 自动管理历史）

    使用 astream(stream_mode=["messages", "custom"]) 获取：
    - 文本 token 流
    - 工具调用状态（通过 get_stream_writer）
    """
    try:
        agent = _get_chat_agent(model)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': f'Agent 初始化失败: {str(e)}'}, ensure_ascii=False)}\n\n"
        return

    # 更新工作流状态（供工具读取）
    state = workflow_state or {}
    _set_workflow_state(chat_session_id, state)

    # 构建运行时配置（model 已内置到 agent，config 仅需 thread_id）
    config: RunnableConfig = {
        "configurable": {
            "thread_id": chat_session_id,
        }
    }

    # 注入简短进度提示
    step_hint = _build_step_hint(state)
    enhanced_message = f"{step_hint}\n\n{message}" if step_hint else message

    text_generated = False

    try:
        from langchain.messages import HumanMessage

        async for chunk in agent.astream(
            {"messages": [HumanMessage(content=enhanced_message)]},
            config=config,
            stream_mode=["messages", "custom"],
        ):
            stream_mode, data = chunk

            if stream_mode == "messages":
                token, _ = data
                # 跳过工具调用 chunk
                if isinstance(token, AIMessageChunk):
                    if token.tool_calls or token.tool_call_chunks:
                        continue
                    # 提取文本内容
                    text = ""
                    if isinstance(token.content, str):
                        text = token.content
                    elif isinstance(token.content, list):
                        for block in token.content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text += block.get("text", "")
                    if text:
                        text_generated = True
                        d = json.dumps(
                            {"type": "token", "content": text},
                            ensure_ascii=False,
                        )
                        yield f"data: {d}\n\n"

            elif stream_mode == "custom":
                # 工具状态消息
                status_msg = ""
                if isinstance(data, str):
                    status_msg = data
                elif isinstance(data, dict):
                    status_msg = data.get("message", data.get("status", str(data)))
                if status_msg:
                    d = json.dumps(
                        {"type": "thinking", "message": status_msg},
                        ensure_ascii=False,
                    )
                    yield f"data: {d}\n\n"

        # Guard: if no text was generated, emit a fallback message
        if not text_generated:
            logger.warning("Chat agent completed without generating any text response")
            fallback = json.dumps(
                {
                    "type": "token",
                    "content": "抱歉，助手暂时无法生成回复，请稍后重试。",
                },
                ensure_ascii=False,
            )
            yield f"data: {fallback}\n\n"

        yield 'data: {"type": "done"}\n\n'
    except Exception as e:
        logger.error(f"Chat streaming error: {e}", exc_info=True)
        error_data = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {error_data}\n\n"
