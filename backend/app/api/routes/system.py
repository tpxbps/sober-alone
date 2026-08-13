from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.capabilities import get_capabilities

router = APIRouter(tags=["system"])


@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(get_db)) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}


@router.get("/api/v1/system/capabilities")
async def capabilities() -> dict:
    return get_capabilities()
