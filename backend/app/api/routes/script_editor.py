"""
Script Editor API Routes — 剧本创作工作流 API
"""

import json
import logging
from typing import Any, Optional, cast

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.script_editor.graph import get_script_gen_graph
from app.script_editor.state import STEP_LABELS, INTERRUPT_STEPS, STEP_INIT
from app.script_editor.prompts.defaults import DEFAULT_PROMPTS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/script-editor", tags=["script-editor"])


# === 请求/响应模型 ===


class StartWorkflowRequest(BaseModel):
    user_idea: str
    player_count: int = 4
    difficulty: int = 1
    num_clue_rounds: int = 2
    prompts: Optional[dict] = None  # 用户自定义提示词


class ResumeWorkflowRequest(BaseModel):
    action: str  # "confirm" | "regenerate" | "edit"
    content: Optional[str] = None
    characters: Optional[list] = None
    character_scripts: Optional[dict] = None
    human_review: Optional[str] = None
    game_data_sections: Optional[dict] = None
    prompt: Optional[str] = None  # 更新下一步的提示词


class UpdatePromptRequest(BaseModel):
    prompt: str


class UpdateTitleRequest(BaseModel):
    script_title: str


class DeleteScriptRequest(BaseModel):
    owner_uuid: str


class ForkRequest(BaseModel):
    checkpoint_id: str
    state_updates: Optional[dict] = None


class ChatRequest(BaseModel):
    message: str
    model: str = "deepseek-v4-flash"
    chat_session_id: str
    workflow_thread_id: Optional[str] = None


# === API 端点 ===


@router.post("/start")
async def start_workflow(request: StartWorkflowRequest):
    """启动新的剧本创作工作流"""
    graph = get_script_gen_graph()
    thread_id = _generate_thread_id()
    config = _config(thread_id)

    initial_state = {
        "user_idea": request.user_idea,
        "player_count": request.player_count,
        "difficulty": request.difficulty,
        "num_clue_rounds": request.num_clue_rounds,
    }
    if request.prompts:
        initial_state["prompts"] = request.prompts

    try:
        # 运行到第一个 interrupt
        from app.script_editor.state import ScriptGenState

        result = await graph.ainvoke(cast(ScriptGenState, initial_state), config)

        # 获取当前状态
        state_snapshot = graph.get_state(config)
        state_values = state_snapshot.values
        interrupt_info = _extract_interrupt_info(state_snapshot)

        # 注册 script_id → thread_id 映射（供 SSE 进度推送使用）
        script_id = state_values.get("script_id", "")
        if script_id:
            _register_script_thread(script_id, thread_id)

        return {
            "success": True,
            "thread_id": thread_id,
            "owner_uuid": state_values.get("owner_uuid", ""),
            "script_id": script_id,
            "script_title": state_values.get("script_title", ""),
            "current_step": (
                interrupt_info["step"]
                if interrupt_info
                else state_values.get("current_step", "")
            ),
            "interrupt": interrupt_info,
            "state": _serialize_state_for_response(state_values),
        }
    except Exception as e:
        logger.error(f"Failed to start workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流启动失败: {str(e)}")


@router.get("/{thread_id}/state")
async def get_workflow_state(thread_id: str):
    """获取工作流当前状态"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        state_values = state_snapshot.values

        if not state_values:
            raise HTTPException(status_code=404, detail="工作流不存在")

        interrupt_info = _extract_interrupt_info(state_snapshot)
        is_complete = state_snapshot.next == ()

        return {
            "success": True,
            "thread_id": thread_id,
            "current_step": (
                interrupt_info["step"]
                if interrupt_info
                else state_values.get("current_step", "")
            ),
            "is_complete": is_complete,
            "interrupt": interrupt_info,
            "state": _serialize_state_for_response(state_values),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{thread_id}/resume")
async def resume_workflow(thread_id: str, request: ResumeWorkflowRequest):
    """从 interrupt 恢复工作流"""
    from langgraph.types import Command

    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        # 构建 resume 数据
        resume_data: dict[str, Any] = {
            "action": request.action,
        }
        if request.content is not None:
            resume_data["content"] = request.content
        if request.characters is not None:
            resume_data["characters"] = request.characters
        if request.character_scripts is not None:
            resume_data["character_scripts"] = request.character_scripts
        if request.human_review is not None:
            resume_data["human_review"] = request.human_review
        if request.game_data_sections is not None:
            resume_data["game_data_sections"] = request.game_data_sections

        # 如果用户想更新提示词
        if request.prompt is not None:
            # 先获取当前状态，更新提示词
            state_snapshot = graph.get_state(config)
            current_prompts = state_snapshot.values.get("prompts", {})
            # 根据 action 确定提示词键：regenerate → 当前步骤的生成节点，confirm → 下一步生成节点
            current_step = state_snapshot.values.get("current_step", "")
            prompt_key = _get_prompt_key_for_action(current_step, request.action)
            if prompt_key:
                current_prompts[prompt_key] = request.prompt
                graph.update_state(config, {"prompts": current_prompts})

        # Pre-register script_id → thread_id mapping (for SSE progress during graph execution)
        pre_state = graph.get_state(config)
        pre_script_id = pre_state.values.get("script_id", "")
        if pre_script_id:
            _register_script_thread(pre_script_id, thread_id)

        # 恢复工作流
        result = await graph.ainvoke(Command(resume=resume_data), config)

        # 获取最新状态
        state_snapshot = graph.get_state(config)
        state_values = state_snapshot.values
        interrupt_info = _extract_interrupt_info(state_snapshot)
        is_complete = state_snapshot.next == ()

        # 再次注册（script_id 可能在此轮中首次生成）
        script_id = state_values.get("script_id", "")
        if script_id:
            _register_script_thread(script_id, thread_id)

        return {
            "success": True,
            "thread_id": thread_id,
            "current_step": (
                interrupt_info["step"]
                if interrupt_info
                else state_values.get("current_step", "")
            ),
            "is_complete": is_complete,
            "interrupt": interrupt_info,
            "state": _serialize_state_for_response(state_values),
        }
    except Exception as e:
        logger.error(f"Failed to resume workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流恢复失败: {str(e)}")


@router.put("/{thread_id}/prompt/{step}")
async def update_prompt(thread_id: str, step: str, request: UpdatePromptRequest):
    """更新指定步骤的提示词"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        current_prompts = state_snapshot.values.get("prompts", {})
        current_prompts[step] = request.prompt
        graph.update_state(config, {"prompts": current_prompts})

        return {"success": True, "message": f"提示词已更新: {step}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{thread_id}/title")
async def update_title(thread_id: str, request: UpdateTitleRequest):
    """更新剧本标题"""
    title = request.script_title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        graph.update_state(config, {"script_title": title})
        return {"success": True, "script_title": title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/defaults")
async def get_default_prompts():
    """获取所有步骤的默认提示词"""
    return {
        "success": True,
        "prompts": DEFAULT_PROMPTS,
    }


@router.get("/steps/info")
async def get_steps_info():
    """获取所有步骤的信息（标签、顺序、是否需要确认）"""
    return {
        "success": True,
        "steps": [
            {
                "step": step,
                "label": STEP_LABELS.get(step, step),
                "needs_review": step in INTERRUPT_STEPS,
            }
            for step in [
                "generate_outline",
                "review_outline",
                "generate_first_draft",
                "review_first_draft",
                "review_by_llm",
                "generate_final_draft",
                "review_final",
                "convert_to_game_data",
                "review_game_data",
                "safety_check",
                "save_to_database",
                "generate_assets",
            ]
        ],
    }


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, request: DeleteScriptRequest):
    """删除剧本（需要 owner_uuid 验证）"""
    import aiosqlite
    from app.core.config import settings

    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")

    try:
        async with aiosqlite.connect(db_path) as db:
            # 验证所有权
            cursor = await db.execute(
                "SELECT owner_uuid FROM scripts WHERE script_id = ?",
                (script_id,),
            )
            row = await cursor.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="剧本不存在")

            if row[0] != request.owner_uuid:
                raise HTTPException(status_code=403, detail="无权操作此剧本")

            # 删除相关角色
            await db.execute("DELETE FROM characters WHERE script_id = ?", (script_id,))
            # 删除剧本
            await db.execute("DELETE FROM scripts WHERE script_id = ?", (script_id,))
            await db.commit()

        # 尝试清理 ChromaDB 数据
        try:
            import chromadb
            from chromadb.config import Settings as ChromaSettings
            from app.core.config import settings as app_settings

            client = chromadb.PersistentClient(
                path=app_settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
            collection_name = f"script_{script_id.replace('-', '_')}"
            try:
                client.delete_collection(collection_name)
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Failed to cleanup ChromaDB: {e}")

        # 清理生成的文件资源（音频、图片）
        try:
            import shutil
            from pathlib import Path

            backend_root = Path(__file__).parent.parent.parent.parent
            audio_dir = backend_root / "data" / "audio" / "scripts" / script_id
            image_dir = backend_root / "data" / "images" / "scripts" / script_id
            if audio_dir.exists():
                shutil.rmtree(audio_dir, ignore_errors=True)
            if image_dir.exists():
                shutil.rmtree(image_dir, ignore_errors=True)
        except Exception as e:
            logger.warning(f"Failed to cleanup file resources: {e}")

        return {"success": True, "message": "剧本已删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete script: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/{script_id}/verify-ownership")
async def verify_ownership(script_id: str, owner_uuid: str = Query(...)):
    """验证用户是否拥有某剧本"""
    import aiosqlite
    from app.core.config import settings

    db_path = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "")

    try:
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute(
                "SELECT owner_uuid FROM scripts WHERE script_id = ?",
                (script_id,),
            )
            row = await cursor.fetchone()

            if not row:
                return {"success": True, "is_owner": False}

            return {"success": True, "is_owner": row[0] == owner_uuid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{thread_id}/asset-progress")
async def get_asset_progress_endpoint(thread_id: str):
    """轮询资产生成进度"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            return {"success": True, "progress": None}

        from app.script_editor.nodes.save import get_asset_progress

        progress = get_asset_progress(script_id)
        return {"success": True, "progress": progress}
    except Exception as e:
        logger.error(f"Failed to get asset progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{thread_id}/convert-progress")
async def get_convert_progress_endpoint(thread_id: str):
    """轮询结构化数据转化进度"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            return {"success": True, "progress": None}

        from app.script_editor.nodes.convert import get_convert_progress

        progress = get_convert_progress(script_id)
        return {"success": True, "progress": progress}
    except Exception as e:
        logger.error(f"Failed to get convert progress: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{thread_id}/retry-asset/{task_id}")
async def retry_asset_task(thread_id: str, task_id: str):
    """重试单个失败的资产生成任务"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        from app.script_editor.nodes.save import retry_single_asset
        from app.script_editor.state import ScriptGenState

        await retry_single_asset(
            script_id, task_id, cast(ScriptGenState, state_snapshot.values)
        )

        # Return actual task status after retry
        from app.script_editor.nodes.save import get_asset_progress

        progress = get_asset_progress(script_id)
        task_status = "unknown"
        if progress:
            for phase in progress.get("phases", []):
                for task in phase.get("tasks", []):
                    if task["id"] == task_id:
                        task_status = task["status"]
                        break
        return {
            "success": True,
            "message": f"任务 {task_id} 重试完成",
            "task_status": task_status,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{thread_id}/retry-convert/{task_id}")
async def retry_convert_task(thread_id: str, task_id: str):
    """重试单个失败的结构化数据转化任务"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        # 注册 SSE 映射
        _register_script_thread(script_id, thread_id)

        from app.script_editor.nodes.convert import retry_single_convert
        from app.script_editor.state import ScriptGenState

        await retry_single_convert(
            script_id, task_id, cast(ScriptGenState, state_snapshot.values)
        )

        # Return actual task status after retry
        from app.script_editor.nodes.convert import get_convert_progress

        progress = get_convert_progress(script_id)
        task_status = "unknown"
        if progress:
            for phase in progress.get("phases", []):
                for task in phase.get("tasks", []):
                    if task["id"] == task_id:
                        task_status = task["status"]
                        break
        return {
            "success": True,
            "message": f"转化任务 {task_id} 重试完成",
            "task_status": task_status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Retry convert failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{thread_id}/history")
async def get_workflow_history(thread_id: str):
    """返回工作流的所有检查点（按时间倒序）"""
    graph = get_script_gen_graph()
    config = _config(thread_id)

    try:
        checkpoints = []
        for state in graph.get_state_history(config):
            values = state.values
            if not values:
                continue
            interrupt_info = _extract_interrupt_info(state)
            cfg = (
                state.config.get("configurable", {})
                if isinstance(state.config, dict)
                else {}
            )
            checkpoints.append(
                {
                    "checkpoint_id": cfg.get("checkpoint_id", ""),
                    "current_step": values.get("current_step", ""),
                    "next": list(state.next),
                    "interrupt": interrupt_info,
                    "timestamp": (
                        state.created_at if hasattr(state, "created_at") else None
                    ),
                    "state": _serialize_state_for_response(values),
                }
            )

        return {"success": True, "checkpoints": checkpoints}
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{thread_id}/checkpoint/{checkpoint_id}")
async def get_checkpoint_state(thread_id: str, checkpoint_id: str):
    """返回特定检查点的状态（只读）"""
    graph = get_script_gen_graph()
    config = _config(thread_id, checkpoint_id)

    try:
        state_snapshot = graph.get_state(config)
        if not state_snapshot.values:
            raise HTTPException(status_code=404, detail="检查点不存在")

        interrupt_info = _extract_interrupt_info(state_snapshot)
        return {
            "success": True,
            "checkpoint_id": checkpoint_id,
            "current_step": state_snapshot.values.get("current_step", ""),
            "interrupt": interrupt_info,
            "state": _serialize_state_for_response(state_snapshot.values),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get checkpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{thread_id}/fork")
async def fork_from_checkpoint(thread_id: str, request: ForkRequest):
    """从历史检查点分叉 — 定位到该节点可编辑态"""
    graph = get_script_gen_graph()
    checkpoint_config = _config(thread_id, request.checkpoint_id)

    try:
        # Apply state updates if provided
        if request.state_updates:
            graph.update_state(checkpoint_config, request.state_updates)

        # Get the checkpoint state to determine what phase we're in
        state_snapshot = graph.get_state(checkpoint_config)
        if not state_snapshot.values:
            raise HTTPException(status_code=404, detail="检查点不存在")

        state_values = state_snapshot.values
        current_step = state_values.get("current_step", "")
        next_nodes = list(state_snapshot.next) if state_snapshot.next else []

        # Case 1: Checkpoint is at "init" (idea phase) — return state directly, no re-run
        if current_step == STEP_INIT:
            return {
                "success": True,
                "thread_id": thread_id,
                "current_step": STEP_INIT,
                "is_complete": False,
                "interrupt": None,
                "state": _serialize_state_for_response(state_values),
            }

        # Determine the target interrupt step for this phase
        target_interrupt = _get_phase_interrupt_step(current_step)

        if not target_interrupt:
            # Unknown step, try direct replay
            await graph.ainvoke(None, checkpoint_config)
        elif target_interrupt in next_nodes:
            # Case 2: Checkpoint's next directly leads to the target interrupt
            await graph.ainvoke(None, checkpoint_config)
        else:
            # Case 3: Search history for a checkpoint whose next contains target_interrupt
            found = False
            for hist_state in graph.get_state_history(_config(thread_id)):
                hist_next = list(hist_state.next) if hist_state.next else []
                if target_interrupt in hist_next:
                    await graph.ainvoke(None, hist_state.config)
                    found = True
                    break

            if not found:
                # Fallback: just run from original checkpoint
                await graph.ainvoke(None, checkpoint_config)

        # Get new state
        state_snapshot = graph.get_state(_config(thread_id))
        state_values = state_snapshot.values
        interrupt_info = _extract_interrupt_info(state_snapshot)
        is_complete = state_snapshot.next == ()

        # Re-register SSE mapping
        script_id = state_values.get("script_id", "")
        if script_id:
            _register_script_thread(script_id, thread_id)

        return {
            "success": True,
            "thread_id": thread_id,
            "current_step": (
                interrupt_info["step"]
                if interrupt_info
                else state_values.get("current_step", "")
            ),
            "is_complete": is_complete,
            "interrupt": interrupt_info,
            "state": _serialize_state_for_response(state_values),
        }
    except Exception as e:
        logger.error(f"Failed to fork: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"分叉失败: {str(e)}")


@router.post("/chat")
async def chat_with_assistant(request: ChatRequest):
    """
    与AI创作助手聊天（SSE流式响应）

    使用 create_agent + checkpointer 自动管理历史，
    基于当前工作流状态提供上下文感知的回复。
    """
    # 获取工作流状态作为上下文（如果提供了 workflow_thread_id）
    workflow_state = {}
    if request.workflow_thread_id:
        graph = get_script_gen_graph()
        config = _config(request.workflow_thread_id)
        try:
            state_snapshot = graph.get_state(config)
            if state_snapshot and state_snapshot.values:
                workflow_state = state_snapshot.values
        except Exception:
            pass

    from app.script_editor.services.chat_service import stream_chat_response

    return StreamingResponse(
        stream_chat_response(
            message=request.message,
            model=request.model,
            chat_session_id=request.chat_session_id,
            workflow_state=workflow_state,
        ),
        media_type="text/event-stream",
    )


@router.get("/{thread_id}/progress-stream")
async def progress_stream(thread_id: str):
    """SSE 进度流 — 向前端实时推送 convert/asset 进度"""
    import asyncio
    import json
    from app.script_editor.services.progress_bus import subscribe, unsubscribe

    queue = subscribe(thread_id)

    async def event_generator():
        try:
            # 立即发送初始连接确认
            yield f"data: {json.dumps({'type': 'connected'}, ensure_ascii=False)}\n\n"

            # 发送当前进度快照（解决 SSE 连接晚于任务启动的问题）
            try:
                graph = get_script_gen_graph()
                state_snapshot = graph.get_state(_config(thread_id))
                script_id = state_snapshot.values.get("script_id", "")
                if script_id:
                    from app.script_editor.nodes.convert import get_convert_progress
                    from app.script_editor.nodes.save import get_asset_progress

                    convert_prog = get_convert_progress(script_id)
                    if convert_prog:
                        yield f"data: {json.dumps({'type': 'convert_progress', 'data': convert_prog}, ensure_ascii=False)}\n\n"

                    asset_prog = get_asset_progress(script_id)
                    if asset_prog:
                        yield f"data: {json.dumps({'type': 'asset_progress', 'data': asset_prog}, ensure_ascii=False)}\n\n"
            except Exception:
                pass

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                    # 如果是 complete 事件，再发送后结束
                    data = event.get("data")
                    if isinstance(data, dict) and data.get("isComplete"):
                        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                        break
                except asyncio.TimeoutError:
                    # 心跳包，防止连接超时断开
                    yield f": heartbeat\n\n"
        finally:
            unsubscribe(thread_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# === 辅助函数 ===


def _generate_thread_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _config(thread_id: str, checkpoint_id: str | None = None) -> RunnableConfig:
    """Build a RunnableConfig for LangGraph operations."""
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if checkpoint_id is not None:
        configurable["checkpoint_id"] = checkpoint_id
    return cast(RunnableConfig, {"configurable": configurable})


def _extract_interrupt_info(state_snapshot) -> dict | None:
    """从状态快照中提取 interrupt 信息。
    优先从 tasks 中获取，若无则根据 next 节点和 state 值重建（支持页面刷新/中断恢复）。"""
    # 尝试从 tasks 获取（正常 interrupt 流程）
    if state_snapshot.tasks:
        for task in state_snapshot.tasks:
            if task.interrupts:
                interrupt = task.interrupts[0]
                value = interrupt.value
                if isinstance(value, dict):
                    info = {
                        "step": value.get("step", ""),
                        "step_label": value.get("step_label", ""),
                        "generated_content": value.get("generated_content", ""),
                        "characters": value.get("characters", []),
                        "character_scripts": value.get("character_scripts", {}),
                        "review_opinion": value.get("review_opinion", ""),
                        "game_data_sections": value.get("game_data_sections", {}),
                        "prompt_used": value.get("prompt_used", ""),
                        "rejected": value.get("rejected", False),
                        "reason": value.get("reason", ""),
                    }
                    # 验证 game_data_sections 数据量
                    gds = info.get("game_data_sections", {})
                    if gds and info["step"] == "review_game_data":
                        logger.info(
                            f"interrupt game_data_sections: "
                            f"opening={len(gds.get('opening', ''))}, "
                            f"clue_stages={len(gds.get('clue_stages', []))}, "
                            f"truth_reveal={len(gds.get('truth_reveal', ''))}, "
                            f"full_truth={len(gds.get('full_truth', ''))}, "
                            f"game_flow={len(gds.get('game_flow', []))}, "
                            f"character_scripts={len(gds.get('character_scripts', {}))}, "
                            f"character_data={len(gds.get('character_data', []))}"
                        )
                    return info

    # 降级：根据 next 节点判断当前中断步骤，从 state 值重建 interrupt 信息
    state_values = state_snapshot.values if hasattr(state_snapshot, "values") else {}
    next_nodes = state_snapshot.next if hasattr(state_snapshot, "next") else ()

    # next_nodes 包含当前正在执行/等待的节点名
    # review nodes 就是 interrupt 点
    for node_name in next_nodes:
        if node_name in INTERRUPT_STEPS:
            return _reconstruct_interrupt_info(node_name, state_values)

    # 如果 current_step 本身就是 review 步骤（不太常见但作为保险）
    current_step = state_values.get("current_step", "")
    if current_step in INTERRUPT_STEPS:
        return _reconstruct_interrupt_info(current_step, state_values)

    return None


def _reconstruct_interrupt_info(step: str, state: dict) -> dict:
    """从 state 值重建 interrupt 信息（用于服务重启/内存丢失后的恢复）"""
    label = STEP_LABELS.get(step, step)
    prompts = state.get("prompts", {})

    info = {
        "step": step,
        "step_label": label,
        "generated_content": "",
        "characters": state.get("characters", []),
        "character_scripts": state.get("character_scripts", {}),
        "review_opinion": state.get("review_opinion", ""),
        "game_data_sections": state.get("game_data_sections", {}),
        "prompt_used": "",
        "rejected": False,
        "reason": "",
    }

    if step == "review_outline":
        info["generated_content"] = state.get("outline", "")
        info["prompt_used"] = prompts.get("generate_outline", "")
    elif step == "review_first_draft":
        info["generated_content"] = state.get("first_draft", "")
        info["prompt_used"] = prompts.get("generate_first_draft", "")
    elif step == "review_final":
        info["generated_content"] = state.get("final_draft", "")
        info["prompt_used"] = prompts.get("generate_final_draft", "")
    elif step == "review_game_data":
        info["prompt_used"] = prompts.get("convert_to_game_data", "")
    elif step == "safety_check":
        info["rejected"] = not state.get("safety_passed", False)

    return info


def _serialize_state_for_response(state_values: dict) -> dict:
    """序列化状态数据用于 API 响应（过滤敏感/大数据）"""
    # 只返回前端需要的字段
    return {
        "script_title": state_values.get("script_title", ""),
        "script_id": state_values.get("script_id", ""),
        "owner_uuid": state_values.get("owner_uuid", ""),
        "user_idea": state_values.get("user_idea", ""),
        "player_count": state_values.get("player_count", 4),
        "difficulty": state_values.get("difficulty", 1),
        "num_clue_rounds": state_values.get("num_clue_rounds", 2),
        "outline": state_values.get("outline", ""),
        "characters": state_values.get("characters", []),
        "first_draft": state_values.get("first_draft", ""),
        "review_opinion": state_values.get("review_opinion", ""),
        "final_draft": state_values.get("final_draft", ""),
        "character_scripts": state_values.get("character_scripts", {}),
        "game_data_sections": state_values.get("game_data_sections", {}),
        "prompts": state_values.get("prompts", {}),
        "cover_image_url": state_values.get("cover_image_url", ""),
        "character_avatars": state_values.get("character_avatars", {}),
        "error_message": state_values.get("error_message", ""),
        "safety_passed": state_values.get("safety_passed", False),
    }


def _get_prompt_key_for_action(current_step: str, action: str) -> str | None:
    """根据当前审阅步骤和操作类型，确定应更新哪个步骤的提示词

    - regenerate: 更新当前审阅步骤对应的生成节点提示词（重新生成当前内容）
    - confirm: 更新下一步生成节点的提示词
    """
    # Regenerate → 更新当前步骤对应的生成节点
    regen_map = {
        "review_outline": "generate_outline",
        "review_first_draft": "generate_first_draft",
        "review_final": "generate_final_draft",
        "review_game_data": "convert_to_game_data",
    }
    # Confirm → 更新下一步生成节点
    confirm_map = {
        "review_outline": "generate_first_draft",
        "review_first_draft": None,  # next is review_by_llm (no user prompt)
        "review_final": "convert_to_game_data",
        "review_game_data": None,  # no next generation step
    }

    if action == "regenerate":
        return regen_map.get(current_step)
    return confirm_map.get(current_step)


def _register_script_thread(script_id: str, thread_id: str):
    """注册 script_id → thread_id 映射，供 SSE 进度推送使用"""
    from app.script_editor.nodes.convert import register_script_thread as _reg_convert
    from app.script_editor.nodes.save import register_script_thread as _reg_save

    _reg_convert(script_id, thread_id)
    _reg_save(script_id, thread_id)


def _get_phase_interrupt_step(current_step: str) -> str | None:
    """Map any step to its phase's interrupt/review step.

    This ensures that when forking back to a completed phase,
    we find the checkpoint that will land at the correct interrupt.
    """
    mapping = {
        STEP_INIT: None,
        "generate_outline": "review_outline",
        "review_outline": "review_outline",
        "generate_first_draft": "review_first_draft",
        "review_first_draft": "review_first_draft",
        "review_by_llm": "review_final",
        "generate_final_draft": "review_final",
        "review_final": "review_final",
        "convert_to_game_data": "review_game_data",
        "review_game_data": "review_game_data",
        "safety_check": "safety_check",
    }
    return mapping.get(current_step)
