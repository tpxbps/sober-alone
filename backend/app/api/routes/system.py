from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.readiness import DatabaseNotInitializedError, ensure_database_ready
from app.db.session import get_db
from app.services.capabilities import get_capabilities

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
