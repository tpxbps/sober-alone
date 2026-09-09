from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.readiness import DatabaseNotInitializedError, ensure_database_ready
from app.db.session import get_db
from app.services.capabilities import get_capabilities
from app.services.model_health import get_model_health

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await ensure_database_ready(db)
    except DatabaseNotInitializedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "database": "ok"}


@router.get("/api/v1/system/capabilities")
async def capabilities() -> dict:
    return get_capabilities()


@router.get("/api/v1/system/model-health")
async def model_health() -> dict:
    return await get_model_health(wait_for_completion=False)


@router.post("/api/v1/system/model-health/refresh")
async def refresh_model_health() -> dict:
    return await get_model_health(force_refresh=True, wait_for_completion=False)
