"""Per-invocation knowledge and tool boundaries, including restored agents."""

from langchain.agents.middleware import AgentMiddleware
from langchain.messages import HumanMessage, SystemMessage

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
        fact = str(clues[0].get("content") or clues[0].get("summary") or "").split("\n")[0]
        fact = fact.split("。")[0][:100].replace("[", "（").replace("]", "）")
        parts.append(f"""【本次最终发言的引用格式｜工具调用后仍须遵守】
有证据的事实或推理句写成 [完整原话][ID]；多项依据写成 [完整原话][ID,ID]。
只要本次发言包含基于带 ID 线索条目的判断，至少把其中一个核心判断写成关联引用。
仅点名一条材料时才用 [{example}]；不要把句末几个直接标签当作关联引用。
例如，直接点名：我想核实一下[{example}]。
例如，根据当前已公开材料附证据：[{fact}][{example}]。
多依据格式为 [你自己的完整推理][{evidence_ids}]，只有这些材料确实支持该句时才能合并使用。
先输出左方括号 [，再写完整原话，再输出 ][ID]；不要先写完原话才想起补标签。
旧消息的格式不是模板。第一组括号只放自然语言，不嵌套标签、不写裸 ID；第二组只放已公开 ID，用英文逗号分隔，且仅有一组。
不要用反引号包裹引用，不写参考文献列表，不输出格式检查过程。无 ID 的轮次说明直接说明来源，不编造证据引用。
""")
    if stage == "clue_analysis":
        parts.append("可调用 update_role_reaction 更新心理反应，完成工具调用后再发言。")
    if stage == "vote":
        parts.append("本阶段通过 submit_final_vote 提交最终投票。")
    return "\n\n".join(parts)


class StagePolicyMiddleware(AgentMiddleware):
    def prepare(self, request):
        from app.agents.speech_attempt import current_speech_attempt

        current_speech_attempt()  # Reject late model calls from cancelled attempts.
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
        messages = [clean_message(message) for message in request.messages]
        if clues:
            # This is invocation-local guidance, not a new turn in saved memory.
            # Place it after tool results too, where the final response is decided.
            messages.append(
                HumanMessage(
                    content=(
                        "本轮最终发言：先给出一句有公开证据支持的事实或推理，"
                        "用 [这句完整原话][对应ID] 写出来，再继续讨论。"
                        "只引用确实支持该句的已公开材料；没有依据时直接说明，不编造引用。"
                    )
                )
            )
        return request.override(
            tools=[tool for tool in request.tools if tool.name in allowed],
            messages=messages,
            system_message=SystemMessage(
                content=base + ("\n\n" + instructions if instructions else "")
            ),
        )

    def wrap_model_call(self, request, handler):
        return handler(self.prepare(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self.prepare(request))
