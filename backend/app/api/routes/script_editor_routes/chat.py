"""Context-aware script editor assistant route."""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.schemas.script_editor import ChatRequest
from app.script_editor.graph import get_script_gen_graph
from app.script_editor.services.workflow_service import ScriptEditorWorkflowService

router = APIRouter()


@router.post("/chat")
async def chat_with_assistant(request: ChatRequest):
    """Stream a context-aware assistant response over SSE."""
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
