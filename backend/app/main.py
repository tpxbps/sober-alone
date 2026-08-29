import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.agent_manager import prune_agent_managers
from app.api.routes import game, script_editor, system
from app.core.config import settings
from app.db.readiness import ensure_database_ready
from app.db.session import engine
from app.script_editor.graph import set_script_gen_graph
from app.script_editor.services.operation_service import editor_operation_runner
from app.services.checkpoint_runtime import set_game_checkpointer
from app.services.game_service import prune_flow_controllers


async def _runtime_janitor(stop: asyncio.Event) -> None:
    """Release only idle process objects; durable games and checkpoints remain."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=3600)
        except TimeoutError:
            max_idle = timedelta(hours=72)
            expired = set(prune_flow_controllers(max_idle))
            expired.update(prune_agent_managers(max_idle))
            from app.services.game_speech import release_speech_lock

            for session_id in expired:
                release_speech_lock(session_id)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Fail fast with an actionable message when migrations were skipped."""

    async with engine.connect() as connection:
        await ensure_database_ready(connection)
    settings.local_data_dir.mkdir(parents=True, exist_ok=True)
    async with (
        AsyncSqliteSaver.from_conn_string(str(settings.workflow_checkpoint_path)) as workflows,
        AsyncSqliteSaver.from_conn_string(str(settings.game_checkpoint_path)) as games,
    ):
        await workflows.setup()
        await games.setup()
        set_script_gen_graph(workflows)
        set_game_checkpointer(games)
        await editor_operation_runner.recover_pending()
        stop = asyncio.Event()
        janitor = asyncio.create_task(_runtime_janitor(stop))
        try:
            yield
        finally:
            stop.set()
            await janitor
            await editor_operation_runner.shutdown()
            set_game_checkpointer(None)


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
