"""Per-invocation knowledge and tool boundaries, including restored agents."""

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import SystemMessage

from app.game.clues import build_agent_clue_context, parse_clue_citations, stage_public_clues


def available_tool_names(state):
    names = {"recall_personal_script_memory"}
    stage = state.get("current_stage", "")
    if stage_public_clues(stage, state.get("public_clues", [])):
        names.add("recall_public_clues")
    if stage == "clue_analysis":
        names.add("update_role_reaction")
    if stage == "vote":
        names.add("submit_final_vote")
    return names


def stage_instructions(state):
    stage = state.get("current_stage", "")
    clues = stage_public_clues(stage, state.get("public_clues", []))
    parts = []
    if clues:
        example = clues[0]["id"]
        parts.append(f"""【本轮引用格式】
当且仅当发言依据下方已公开内容时，紧跟相关句子附上纯文本短标签，例如 [{example}]。
正文直接说事实或摘要，不要把机器 ID 当作线索名称。不要在标签两侧添加反引号、粗体或内部链接。
不要把引用集中堆在结尾；不得编造其他 ID。记忆不清时先调用 recall_public_clues 核对。
""")
        parts.append(build_agent_clue_context(clues))
    if stage == "clue_analysis":
        parts.append("可调用 update_role_reaction 更新心理反应，完成工具调用后再发言。")
    if stage == "vote":
        parts.append("本阶段通过 submit_final_vote 提交最终投票。")
    return "\n\n".join(parts)


class StagePolicyMiddleware(AgentMiddleware):
    def prepare(self, request):
        allowed = available_tool_names(request.state)
        instructions = stage_instructions(request.state)
        clues = stage_public_clues(
            request.state.get("current_stage", ""), request.state.get("public_clues", [])
        )

        def clean(text):
            return parse_clue_citations("§" + text + "§", clues, strip_unknown=True)[0][1:-1]

        def clean_message(message):
            content = message.content
            if isinstance(content, str):
                content = clean(content)
            elif isinstance(content, list):
                content = [
                    {**block, "text": clean(block["text"])}
                    if isinstance(block, dict) and block.get("type") == "text"
                    else block
                    for block in content
                ]
            return message.model_copy(update={"content": content})

        base = clean(request.system_message.text) if request.system_message else ""
        return request.override(
            tools=[tool for tool in request.tools if tool.name in allowed],
            messages=[clean_message(message) for message in request.messages],
            system_message=SystemMessage(
                content=base + ("\n\n" + instructions if instructions else "")
            ),
        )

    def wrap_model_call(self, request, handler):
        return handler(self.prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self.prepare(request))
