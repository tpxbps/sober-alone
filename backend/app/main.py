from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import game, script_editor, system
from app.core.config import settings
from app.db.readiness import ensure_database_ready
from app.db.session import engine


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast with an actionable message when migrations were skipped."""

    async with engine.connect() as connection:
        await ensure_database_ready(connection)
    yield


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-powered Murder Mystery Game API",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(game.router, prefix=settings.API_V1_PREFIX)
app.include_router(script_editor.router, prefix=settings.API_V1_PREFIX)
app.include_router(system.router)

# Mount static audio files directory
_audio_dir = settings.audio_dir
_audio_dir.mkdir(parents=True, exist_ok=True)
if (_audio_dir).exists():
    app.mount("/audio", StaticFiles(directory=str(_audio_dir)), name="audio")

# Mount static image files directory
_image_dir = settings.image_dir
_image_dir.mkdir(parents=True, exist_ok=True)
if (_image_dir).exists():
    app.mount("/images", StaticFiles(directory=str(_image_dir)), name="images")
