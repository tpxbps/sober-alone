import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.api.routes import game

# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="AI-powered Murder Mystery Game API",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(game.router, prefix=settings.API_V1_PREFIX)

# Mount static audio files directory
_audio_dir = Path(__file__).parent.parent / "data" / "audio"
_audio_dir.mkdir(parents=True, exist_ok=True)
if (_audio_dir).exists():
    app.mount("/audio", StaticFiles(directory=str(_audio_dir)), name="audio")
