"""Local single-user script lifecycle routes."""

import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import bindparam, delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import remove_agent_manager
from app.api.schemas.script_editor import LegacyOwnershipClaimRequest
from app.core.config import settings
from app.db.models import Character, GameSession, Script
from app.db.session import get_db
from app.script_editor.editing import hydrate_completed_script
from app.script_editor.graph import get_script_gen_graph
from app.script_editor.ownership import owner_hash_matches, require_author_key_hash
from app.script_editor.services.operation_service import editor_operation_runner
from app.script_editor.services.progress_registry import (
    asset_progress_registry,
    convert_progress_registry,
)
from app.script_editor.services.workflow_service import (
    WorkflowAuthorizationError,
)
from app.services.checkpoint_runtime import delete_game_checkpoints
from app.services.game_service import remove_flow_controller

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/legacy-ownership/claim")
async def claim_legacy_ownership(
    request: LegacyOwnershipClaimRequest,
    db: AsyncSession = Depends(get_db),
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """One-time bridge from legacy browser IDs to the private author key."""

    if not settings.ALLOW_LEGACY_OWNER_CLAIM:
        raise HTTPException(status_code=403, detail="旧版剧本恢复入口未开启")

    columns = {str(row[1]) for row in (await db.execute(text("PRAGMA table_info(scripts)"))).all()}
    if "owner_uuid" not in columns:
        return {"success": True, "claimed_count": 0, "matched_count": 0}

    legacy_ids = sorted({str(owner_uuid) for owner_uuid in request.legacy_owner_uuids})
    update_statement = text(
        """
        UPDATE scripts
        SET owner_key_hash = :owner_key_hash
        WHERE owner_key_hash IS NULL AND owner_uuid IN :legacy_ids
        """
    ).bindparams(bindparam("legacy_ids", expanding=True))
    result = await db.execute(
        update_statement,
        {"owner_key_hash": owner_key_hash, "legacy_ids": legacy_ids},
    )
    matched_statement = text(
        """
        SELECT COUNT(*) FROM scripts
        WHERE owner_key_hash = :owner_key_hash AND owner_uuid IN :legacy_ids
        """
    ).bindparams(bindparam("legacy_ids", expanding=True))
    matched_count = int(
        (
            await db.execute(
                matched_statement,
                {"owner_key_hash": owner_key_hash, "legacy_ids": legacy_ids},
            )
        ).scalar_one()
    )
    await db.commit()
    claimed_count = max(0, int(result.rowcount or 0))
    if claimed_count:
        logger.info("Recovered ownership for %s legacy script(s)", claimed_count)
    return {
        "success": True,
        "claimed_count": claimed_count,
        "matched_count": matched_count,
    }


@router.delete("/scripts/{script_id}")
async def delete_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Delete a script and all locally owned dependent runtime data."""
    try:
        existing = await db.scalar(select(Script).where(Script.script_id == script_id))
        if not existing:
            raise HTTPException(status_code=404, detail="剧本不存在")
        if not owner_hash_matches(existing.owner_key_hash, owner_key_hash):
            raise HTTPException(status_code=403, detail="无权删除该剧本")

        session_rows = list(
            (
                await db.execute(
                    select(GameSession.session_id, GameSession.runtime_snapshot).where(
                        GameSession.script_id == script_id
                    )
                )
            ).all()
        )

        await db.execute(delete(Script).where(Script.script_id == script_id))
        await db.commit()

        for session_id, runtime_snapshot in session_rows:
            characters = (runtime_snapshot or {}).get("characters", [])
            await delete_game_checkpoints(
                session_id,
                [
                    str(item.get("character_id", ""))
                    for item in characters
                    if item.get("character_id")
                ],
            )
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
                try:
                    await checkpointer.adelete_thread(thread_id)
                except Exception as cleanup_error:  # noqa: BLE001 - deletion is already committed
                    logger.warning(
                        "Unable to clean workflow checkpoint thread=%s: %s",
                        thread_id,
                        cleanup_error,
                    )
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


@router.post("/scripts/{script_id}/edit", status_code=202)
async def edit_script(
    script_id: str,
    db: AsyncSession = Depends(get_db),
    owner_key_hash: str = Depends(require_author_key_hash),
):
    """Open a completed owned script directly at structured-data review."""
    script = await db.scalar(select(Script).where(Script.script_id == script_id))
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    characters = list(
        await db.scalars(
            select(Character)
            .where(Character.script_id == script_id)
            .order_by(Character.character_id)
        )
    )
    try:
        if not owner_hash_matches(script.owner_key_hash, owner_key_hash):
            raise WorkflowAuthorizationError("无权编辑该剧本")
        initial_state = hydrate_completed_script(script, characters, owner_key_hash)
        return await editor_operation_runner.queue_edit(
            initial_state=initial_state,
            owner_key_hash=owner_key_hash,
            script_id=script_id,
        )
    except WorkflowAuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


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
