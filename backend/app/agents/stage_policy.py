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
        evidence_ids = ",".join(clue["id"] for clue in clues[:2])
        parts.append(f"""【本轮引用格式】
有两种不同用途的引用，请根据发言内容选择：
1. 直接点名线索：[{example}]，界面会显示它的线索名称，例如“[{example}]里记录了什么？”。
2. 为一句事实或推理附证据：[你的推理文字][{evidence_ids}]。第一对方括号包住完整的推理文字，紧接第二对方括号列出依据 ID，多个 ID 用英文逗号分隔。
写出基于多条线索的综合判断时，优先使用第 2 种格式；句中分别插入多个 [ID] 标签不能替代关联引用。
格式示意：“[{example}]还有疑点。[这两条记录之间的联系仍需核实][{evidence_ids}]。”示意只说明语法，请用实际依据和你的判断替换文字。
只在确有依据处引用；关联引用保留你的原话，显示证据数量，不把文字替换成线索名。
不得把机器 ID 当作线索名称。不要在引用外添加反引号或内部链接。
不要把引用集中堆在结尾；不得编造其他 ID。记忆不清时先调用 recall_public_clues 核对。
""")
        parts.append(build_agent_clue_context(clues))
        parts.append(
            "【发言输出检查】点名时只包住一个 ID；为推理附证据时，用两组紧邻的方括号分别包住推理原文和依据 ID。"
            f"完整形式：[这里写你的完整推理句][{evidence_ids}]。第一组括号不可省略。"
        )
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
