"""Pure response mapping for the GameService compatibility facade."""

from __future__ import annotations

from typing import Any


class GameStatePresenter:
    @staticmethod
    def script(script_data: dict[str, Any] | None) -> dict[str, Any] | None:
        if not script_data:
            return None
        return {
            "script_id": script_data.get("script_id"),
            "title": script_data.get("title"),
            "description": script_data.get("description"),
            "overview": script_data.get("overview"),
            "tags": script_data.get("tags"),
            "difficulty": script_data.get("difficulty"),
            "player_count": script_data.get("player_count"),
            "cover_image_url": script_data.get("cover_image_url"),
        }

    @staticmethod
    def characters(
        characters: list[dict[str, Any]], human_character_id: str
    ) -> list[dict[str, Any]]:
        return [
            {
                "character_id": character.get("character_id"),
                "name": character.get("name"),
                "gender": character.get("gender"),
                "age": character.get("age"),
                "occupation": character.get("occupation"),
                "profile": character.get("profile"),
                "avatar_url": character.get("avatar_url"),
                "voice_id": character.get("voice_id"),
                "is_human": character.get("character_id") == human_character_id,
                "character_script": (
                    character.get("character_script")
                    if character.get("character_id") == human_character_id
                    else None
                ),
                "character_script_summary": character.get("character_script_summary"),
                "system_prompt": (
                    character.get("system_prompt")
                    if character.get("character_id") == human_character_id
                    else None
                ),
            }
            for character in characters
        ]
