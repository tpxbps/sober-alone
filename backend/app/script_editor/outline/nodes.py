"""One model invocation per graph node; the interrupt node has no model calls."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from copy import deepcopy

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.core.config import settings
from app.core.llm_factory import create_llm
from app.script_editor.outline.contracts import Direction, OutlineCheck
from app.script_editor.outline.runtime import current_runtime
from app.script_editor.prompts.templates import get_prompt

REQUIRED_COVERAGE = (
    "background",
    "case",
    "relationships",
    "culprit",
    "motive",
    "method",
    "timeline",
    "ending",
)


def session_of(state: dict) -> dict:
    return deepcopy(state["outline_session"])


def context(state: dict, session: dict) -> str:
    # Deliberately omit assistant chat, discarded branches and unselected alternatives.
    decisions = [
        {
            "source": d["source"],
            "choice": d.get("choice", ""),
            "other_text": d.get("other_text", ""),
        }
        for d in session["decisions"]
    ]
    return json.dumps(
        {
            "原始创意": state.get("user_idea", ""),
            "创作参数": {
                k: state.get(k)
                for k in ("player_count", "difficulty", "num_clue_rounds", "ending_mode")
            },
            "创作要求": get_prompt("generate_outline", state),
            "有效大纲": state.get("outline", ""),
            "已确认决策": decisions,
            "未决事项": session["unresolved"],
        },
        ensure_ascii=False,
    )


def llm(temperature: float):
    return create_llm(
        model=getattr(settings, "SCRIPT_EDITOR_MODEL", None) or "deepseek-flash",
        temperature=temperature,
        disable_thinking=True,
        timeout=120,
        max_retries=0,
    )


async def structured(schema, system: str, content: str):
    messages = [SystemMessage(content=system), HumanMessage(content=content)]
    runtime = current_runtime.get()
    for attempt in range(2):
        if runtime:
            runtime.calls += 1
        try:
            result = await asyncio.wait_for(
                llm(0.35)
                .with_structured_output(schema, method="function_calling")
                .ainvoke(messages),
                timeout=150,
            )
            return schema.model_validate(result)
        except (ValueError, TypeError, AttributeError) as error:
            if attempt:
                raise ValueError("结构化结果仍不完整，请重试本轮") from error
            messages.append(
                HumanMessage(
                    content=f"上一结果未通过格式校验：{str(error)[:500]}。请严格返回完整结构。"
                )
            )
    raise ValueError("未返回结构化结果")


async def stream_text(state: dict, session: dict, task: str, segment_id: str, status: str) -> str:
    runtime = current_runtime.get()
    if runtime:
        await runtime.begin(session, status, segment_id)
        runtime.calls += 1
    chunks = []
    async with asyncio.timeout(240):
        async for chunk in llm(0.85).astream(
            [
                SystemMessage(
                    content="你是剧本杀编剧。仅完成本轮写作任务，用中文Markdown输出正文。不要提问、不要输出JSON、不要展示内部推理。已确认的用户决策必须遵守。"
                ),
                HumanMessage(content=context(state, session) + "\n\n本轮任务：" + task),
            ]
        ):
            text = chunk.content
            if isinstance(text, list):
                text = "".join(
                    b.get("text", "")
                    for b in text
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if text:
                chunks.append(text)
                if runtime:
                    await runtime.token(text)
    result = "".join(chunks).strip()
    if not result:
        raise ValueError("本轮未生成正文，请重试")
    return result


async def write_segment(state: dict) -> dict:
    session = session_of(state)
    if session.get("status") in {"ready", "needs_revision"}:
        session.update(repairs=0, check=None, next_action="finalize")
        return {"outline_session": session, "current_step": "generate_outline"}
    segment_id = f"r{session['revision']}-s{len(session['segments']) + 1}"
    text = await stream_text(state, session, session["next_task"], segment_id, "writing")
    segment = {"id": segment_id, "content": text}
    session["segments"].append(segment)
    session.update(status="directing", next_action="direct")
    if session.get("questions_stopped") or session["questions_asked"] >= 5:
        session["automatic_segments"] += 1
    outline = "\n\n".join(s["content"] for s in session["segments"])
    runtime = current_runtime.get()
    if runtime:
        await runtime.update(session, "outline_segment_complete")
    return {"outline_session": session, "outline": outline, "current_step": "generate_outline"}


async def direct_outline(state: dict) -> dict:
    session = session_of(state)
    runtime = current_runtime.get()
    stopped = session.get("questions_stopped", False)
    if runtime:
        await runtime.begin(session, "directing")
        stopped = stopped or runtime.control.get("questions_stopped", False)
    session["questions_stopped"] = stopped
    if session["automatic_segments"] >= 4 or len(session["segments"]) >= 10:
        session.update(next_action="finalize", status="finalizing")
        return {"outline_session": session}
    can_ask = not stopped and session["questions_asked"] < 5
    result = await structured(
        Direction,
        "你是大纲共创的调度编辑，只返回结构化结果。每次最多询问一个显著影响案件冲突、人物关系、真相动机或反转的问题。通常3–5问，但创意已明确的内容不重复问，次要细节自行补全。"
        "问题必须有独立引导标题title、问题正文question、2–4个options（id/label/impact），并在question对象上返回recommended_option_id，值为某个选项id。"
        "未选中的方向不能写进正文。next_task是回答之后要写的200–400字分段任务。"
        "信息足够时finalize；尚有内容待补全可continue，ai_decisions只记录本轮新确定且需要保留的剧情事实，不重复旧决定，不把未来可选线索清单当成已确认要求。",
        context(state, session) + f"\n允许提问：{can_ask}。已问{session['questions_asked']}题。",
    )
    # Re-read after the model call: stop_questions may arrive while it was running.
    if runtime:
        stopped = stopped or (await runtime.read_control()).get("questions_stopped", False)
    session.update(unresolved=result.unresolved, questions_stopped=stopped)
    for choice in result.ai_decisions:
        session["decisions"].append(
            {
                "source": "ai",
                "choice": choice,
                "other_text": "",
                "segment_index": len(session["segments"]),
            }
        )
    if result.action == "ask":
        question = {**result.question.model_dump(), "id": str(uuid.uuid4())}
        session["next_task"] = result.next_task
        if stopped or session["questions_asked"] >= 5:
            option = next(
                o for o in question["options"] if o["id"] == question["recommended_option_id"]
            )
            session["decisions"].append(
                {
                    "source": "ai",
                    "choice": option["label"] + "：" + option["impact"],
                    "other_text": "",
                    "question": question,
                    "option_id": option["id"],
                    "segment_index": len(session["segments"]),
                }
            )
            session.update(next_action="write", pending_question=None, status="writing")
        else:
            session["questions_asked"] += 1
            session.update(next_action="wait", pending_question=question, status="awaiting_answer")
    else:
        session.update(
            next_action="finalize" if result.action == "finalize" else "write",
            next_task=result.next_task,
            status="finalizing" if result.action == "finalize" else "writing",
        )
    return {"outline_session": session, "current_step": "generate_outline"}


async def wait_for_answer(state: dict) -> dict:
    session = session_of(state)
    question = session["pending_question"]
    runtime = current_runtime.get()
    stopped = session.get("questions_stopped", False)
    if runtime:
        stopped = stopped or (await runtime.read_control()).get("questions_stopped", False)
        await runtime.update(session, "outline_question")
    explicit = runtime.answer if runtime else None
    if explicit and explicit.get("question_id") == question["id"]:
        response = explicit
    elif stopped:
        response = {"option_id": question["recommended_option_id"], "source": "ai"}
    else:
        response = interrupt(
            {
                "step": "outline_wait",
                "step_label": "大纲共创",
                "question": question,
                "revision": session["revision"],
            }
        )
    if response.get("question_id", question["id"]) != question["id"]:
        raise ValueError("回答对应的问题已经失效")
    option_id = response.get("option_id")
    option = next((o for o in question["options"] if o["id"] == option_id), None)
    other = response.get("other_text", "").strip()
    if not option and not other:
        raise ValueError("请选择一个方向或输入其他想法")
    session["decisions"].append(
        {
            "source": response.get("source", "user"),
            "question": question,
            "segment_index": len(session["segments"]),
            "option_id": option_id,
            "choice": (option["label"] + "：" + option["impact"]) if option else "",
            "other_text": other,
        }
    )
    request_id = response.get("request_id")
    if request_id:
        session["consumed_requests"].append(request_id)
    session.update(
        pending_question=None, next_action="write", status="writing", questions_stopped=stopped
    )
    return {"outline_session": session, "current_step": "generate_outline"}


async def finalize_outline(state: dict) -> dict:
    session = session_of(state)
    task = (
        "整理为一份完整可供下一阶段使用的大纲，覆盖标题、背景、案件、角色概要、关系、真凶动机手法、时间线、分轮线索和结局。"
        "严格匹配人数、线索轮数、单/多结局及已确认方向；补齐未决事项。以 '# 标题' 开始；不要把讨论过程、选项、提问写入最终大纲。"
    )
    if session.get("check"):
        task += (
            "\n仅修订检查指出的真实问题，保持其它既定剧情不变，不增添新的机关或线索；输出修订后的完整大纲。问题："
            + json.dumps(session["check"]["issues"], ensure_ascii=False)
        )
    text = await stream_text(state, session, task, "final", "finalizing")
    title_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    session.update(status="checking", next_action="check", final_outline=text)
    runtime = current_runtime.get()
    if runtime:
        await runtime.update(session, "outline_segment_complete")
    return {
        "outline_session": session,
        "outline": text,
        "script_title": title_match.group(1).strip()[:20]
        if title_match
        else state.get("script_title", "未命名剧本"),
        "current_step": "generate_outline",
    }


def check_issues(result: OutlineCheck, state: dict) -> list[str]:
    text = state.get("outline", "")

    def normalize(value):
        # Evidence often quotes rendered Markdown, without bold/code delimiters.
        return re.sub(r"[\s*_`]", "", value)

    normalized = normalize(text)
    issues = list(result.issues)

    def present(quote):
        return bool(quote.strip()) and normalize(quote) in normalized

    for key in REQUIRED_COVERAGE:
        if not present(result.coverage.get(key, "")):
            issues.append(f"缺少可核实的 {key} 内容")
    for label, items, count in [
        ("角色", result.characters, state.get("player_count", 4)),
        ("线索轮次", result.clue_rounds, state.get("num_clue_rounds", 2)),
    ]:
        if len(items) != count or len({i.name for i in items}) != count:
            issues.append(f"{label}数量应为{count}")
        if any(not present(i.quote) for i in items):
            issues.append(f"{label}依据与大纲不一致")
    if result.ending_mode != state.get("ending_mode", "single"):
        issues.append("结局模式与创作参数不一致")
    return list(dict.fromkeys(issues))


async def check_outline(state: dict) -> dict:
    session = session_of(state)
    runtime = current_runtime.get()
    if runtime:
        await runtime.begin(session, "checking")
    result = await structured(
        OutlineCheck,
        "你是独立剧本编辑。检查大纲完整性、因果时间线、人物嫌疑与线索能否支撑真相，以及是否违背用户决定。"
        "issues只列确实存在、会影响大纲使用的问题，不列已排除的问题，不要求初稿级细节。每项说明最小修正建议。原文依据使用8–30字左右、短而连续的原文片段，不改写、不拼接、不加省略号，不完整时不要编造依据。仅返回结构化检查，不续写正文。",
        context(state, session),
    )
    issues = check_issues(result, state)
    session["check"] = {"issues": issues, "passed": not issues, "evidence": result.model_dump()}
    if issues and session["repairs"] < 2:
        session["repairs"] += 1
        session.update(next_action="finalize", status="finalizing")
    else:
        session.update(next_action="review", status="needs_revision" if issues else "ready")
    if runtime:
        await runtime.update(session)
    return {"outline_session": session, "current_step": "generate_outline"}
