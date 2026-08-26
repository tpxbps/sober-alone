"""Nodes used only by the completed-script editing path."""

from app.script_editor.editing import normalize_game_data, prepare_asset_plan
from app.script_editor.state import ScriptGenState


async def normalize_edited_game_data(state: ScriptGenState) -> dict:
    return normalize_game_data(state)


async def build_asset_plan(state: ScriptGenState) -> dict:
    return prepare_asset_plan(state)
