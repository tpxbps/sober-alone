"""
Script Editor API Routes — 剧本创作工作流 API
"""

import json
import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import remove_agent_manager
from app.api.schemas.script_editor import (
    ChatRequest,
    ForkRequest,
    ResumeWorkflowRequest,
    StartWorkflowRequest,
    UpdatePromptRequest,
    UpdateTitleRequest,
)
from app.db.models import GameSession, Script
from app.db.session import get_db
from app.script_editor.graph import get_script_gen_graph
from app.script_editor.services.workflow_service import (
    ScriptEditorWorkflowService,
    WorkflowNotFoundError,
)
from app.services.game_service import remove_flow_controller

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/script-editor", tags=["script-editor"])


# === API 端点 ===


@router.post("/start")
async def start_workflow(request: StartWorkflowRequest):
    """启动新的剧本创作工作流"""
    try:
        return await ScriptEditorWorkflowService().start(request)
    except Exception as e:
        logger.error(f"Failed to start workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流启动失败: {str(e)}")


@router.get("/{thread_id}/state")
async def get_workflow_state(thread_id: str):
    """获取工作流当前状态"""
    try:
        return ScriptEditorWorkflowService().get_state(thread_id)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as e:
        logger.error(f"Failed to get state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{thread_id}/resume")
async def resume_workflow(thread_id: str, request: ResumeWorkflowRequest):
    """从 interrupt 恢复工作流"""
    try:
        return await ScriptEditorWorkflowService().resume(thread_id, request)
    except Exception as e:
        logger.error(f"Failed to resume workflow: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"工作流恢复失败: {str(e)}")


@router.put("/{thread_id}/prompt/{step}")
async def update_prompt(thread_id: str, step: str, request: UpdatePromptRequest):
    """更新指定步骤的提示词"""
    try:
        return ScriptEditorWorkflowService().update_prompt(thread_id, step, request.prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{thread_id}/title")
async def update_title(thread_id: str, request: UpdateTitleRequest):
    """更新剧本标题"""
    try:
        return ScriptEditorWorkflowService().update_title(thread_id, request.script_title)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompts/defaults")
async def get_default_prompts():
    """获取所有步骤的默认提示词"""
    return ScriptEditorWorkflowService.get_defaults()


@router.get("/steps/info")
async def get_steps_info():
    """获取所有步骤的信息（标签、顺序、是否需要确认）"""
    return ScriptEditorWorkflowService.get_steps()


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a script and all locally owned dependent runtime data."""
    from app.core.config import settings

    try:
        existing = await db.scalar(select(Script.script_id).where(Script.script_id == script_id))
        if not existing:
            raise HTTPException(status_code=404, detail="剧本不存在")

        session_ids = list(
            await db.scalars(
                select(GameSession.session_id).where(GameSession.script_id == script_id)
            )
        )

        await db.execute(delete(Script).where(Script.script_id == script_id))
        await db.commit()

        for session_id in session_ids:
            remove_agent_manager(session_id)
            remove_flow_controller(session_id)

        from app.script_editor.services.progress_registry import (
            asset_progress_registry,
            convert_progress_registry,
        )

        thread_ids = {
            thread_id
            for thread_id in (
                asset_progress_registry.thread_id(script_id),
                convert_progress_registry.thread_id(script_id),
            )
            if thread_id
        }
        checkpointer = getattr(get_script_gen_graph(), "checkpointer", None)
        if checkpointer:
            for thread_id in thread_ids:
                await checkpointer.adelete_thread(thread_id)
        asset_progress_registry.reset(script_id)
        convert_progress_registry.reset(script_id)

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

            audio_dir = settings.audio_dir / "scripts" / script_id
            image_dir = settings.image_dir / "scripts" / script_id
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


@router.get("/{thread_id}/asset-progress")
async def get_asset_progress_endpoint(thread_id: str):
    """轮询资产生成进度"""
    graph = get_script_gen_graph()
    config = ScriptEditorWorkflowService.config(thread_id)

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
    config = ScriptEditorWorkflowService.config(thread_id)

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
    config = ScriptEditorWorkflowService.config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        from app.script_editor.nodes.save import retry_single_asset
        from app.script_editor.state import ScriptGenState

        await retry_single_asset(script_id, task_id, cast(ScriptGenState, state_snapshot.values))

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
    config = ScriptEditorWorkflowService.config(thread_id)

    try:
        state_snapshot = graph.get_state(config)
        script_id = state_snapshot.values.get("script_id", "")
        if not script_id:
            raise HTTPException(status_code=404, detail="工作流不存在")

        # 注册 SSE 映射
        ScriptEditorWorkflowService.register_script_thread(script_id, thread_id)

        from app.script_editor.nodes.convert import retry_single_convert
        from app.script_editor.state import ScriptGenState

        await retry_single_convert(script_id, task_id, cast(ScriptGenState, state_snapshot.values))

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
    try:
        return ScriptEditorWorkflowService().get_history(thread_id)
    except Exception as e:
        logger.error(f"Failed to get history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{thread_id}/checkpoint/{checkpoint_id}")
async def get_checkpoint_state(thread_id: str, checkpoint_id: str):
    """返回特定检查点的状态（只读）"""
    try:
        return ScriptEditorWorkflowService().get_checkpoint(thread_id, checkpoint_id)
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as e:
        logger.error(f"Failed to get checkpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{thread_id}/fork")
async def fork_from_checkpoint(thread_id: str, request: ForkRequest):
    """从历史检查点分叉 — 定位到该节点可编辑态"""
    try:
        return await ScriptEditorWorkflowService().fork(
            thread_id, request.checkpoint_id, request.state_updates
        )
    except WorkflowNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
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
        config = ScriptEditorWorkflowService.config(request.workflow_thread_id)
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

    from app.script_editor.services.progress_bus import subscribe, unsubscribe

    queue = subscribe(thread_id)

    async def event_generator():
        try:
            # 立即发送初始连接确认
            yield f"data: {json.dumps({'type': 'connected'}, ensure_ascii=False)}\n\n"

            # 发送当前进度快照（解决 SSE 连接晚于任务启动的问题）
            try:
                graph = get_script_gen_graph()
                state_snapshot = graph.get_state(ScriptEditorWorkflowService.config(thread_id))
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
                except TimeoutError:
                    # 心跳包，防止连接超时断开
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe(thread_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
