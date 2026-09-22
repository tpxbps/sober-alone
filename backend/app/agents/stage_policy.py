"""Per-invocation knowledge and tool boundaries, including restored agents."""

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import SystemMessage

from app.game.clues import (
    build_agent_clue_context,
    build_round_overview_context,
    parse_clue_citations,
    stage_public_clues,
)


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
    overview_context = build_round_overview_context(
        stage_public_clues(stage, state.get("public_round_overviews", []))
    )
    if overview_context:
        parts.append(overview_context)
    if clues:
        example = clues[0]["id"]
        evidence_ids = ",".join(clue["id"] for clue in clues[:2])
        parts.append(build_agent_clue_context(clues))
        parts.append(f"""【发言中的两种引用语法】
直接引用（点名）：[{example}]。这个标签会显示线索名称。例：我想再核实一下[{example}]。
关联引用（附证据）：[推理原文][{evidence_ids}]。第一组括号圈定被证据支持的原话，第二组括号给出依据 ID。
当你用线索支持一个事实或推理句，而不是点名线索名称时，必须使用关联引用，把该句完整地包在第一组方括号里。多个依据只在第二组括号内用英文逗号分隔。
只要本次发言包含基于带 ID 线索条目的判断，至少把其中一个核心判断写成关联引用；仅在句首或句末点名几条线索不算完成这项要求。仅依据无 ID 的轮次说明时，直接说明来源，不强行关联其他条目。即使玩家只是让你回应观点、没有要求引用，或者旧消息都只用了直接标签，也遵守这条规则。

完整发言格式示例：
我想再核实一下[{example}]。[这些记录之间的联系，还需要更多解释][{evidence_ids}]。

关联引用的第一个字符是左方括号 [，它位于推理文字的第一个字之前。先写 [，再写完整推理，再写 ][，再写依据 ID，最后写 ]。
示例只演示格式；请用本次实际推理与确实支持它的已公开 ID 替换。不要凭空增加引用，不要在引用外包反引号，不要另写参考文献列表。机器 ID 不是线索名称。记忆不清时先调用 recall_public_clues 核对。
引用必须保持单层，严格遵守以下三条：
1. ID 只能出现在直接标签或关联引用的第二组括号中，正文和推理原文中绝不写裸 ID。点名请写“[{example}]那条记录”，不能写“{example}那条记录”。
2. 第一组括号里只写自然语言推理，绝不能再嵌入线索标签或另一组关联引用。想同时点名和解释时，先在括号外写直接标签，再另写关联引用。
3. 一段推理后只能紧接一组依据，所有 ID 合并在这一组内用英文逗号分隔；不要写成“[推理][第一个ID][第二个ID]”。连续直接标签只用于单独点名多条材料。
输出前静默检查：没有裸 ID，没有嵌套方括号，每段推理只有一组依据，所有 ID 都属于当前已公开列表。不要把检查过程写出来。未知 ID 即使出现在历史中，也不能在道歉、反驳或解释时照抄；直接说“那条未公开的线索”。
""")
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
