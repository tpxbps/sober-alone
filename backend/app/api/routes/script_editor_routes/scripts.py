"""Local single-user script lifecycle routes."""

import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import remove_agent_manager
from app.core.config import settings
from app.db.models import GameSession, Script
from app.db.session import get_db
from app.script_editor.graph import get_script_gen_graph
from app.script_editor.services.progress_registry import (
    asset_progress_registry,
    convert_progress_registry,
)
from app.services.game_service import remove_flow_controller

logger = logging.getLogger(__name__)

router = APIRouter()


@router.delete("/scripts/{script_id}")
async def delete_script(script_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a script and all locally owned dependent runtime data."""
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

        _delete_vector_collection(script_id)
        _delete_generated_assets(script_id)

        return {"success": True, "message": "剧本已删除"}
    except HTTPException:
        raise
    except Exception as error:
        await db.rollback()
        logger.error("Failed to delete script: %s", error, exc_info=True)
        raise HTTPException(status_code=500, detail=str(error)) from error


def _delete_vector_collection(script_id: str) -> None:
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        collection_name = f"script_{script_id.replace('-', '_')}"
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
    except Exception as error:
        logger.warning("Failed to clean up ChromaDB: %s", error)


def _delete_generated_assets(script_id: str) -> None:
    try:
        for asset_dir in (
            settings.audio_dir / "scripts" / script_id,
            settings.image_dir / "scripts" / script_id,
        ):
            if asset_dir.exists():
                shutil.rmtree(asset_dir, ignore_errors=True)
    except Exception as error:
        logger.warning("Failed to clean up generated resources: %s", error)
