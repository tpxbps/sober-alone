import pytest

from app.script_editor.graph import _route_after_save
from app.script_editor.nodes import safety_check as safety_module


def test_save_error_skips_optional_asset_generation():
    assert _route_after_save({"error_message": "database is locked"}) == "end"
    assert _route_after_save({"error_message": ""}) == "generate_assets"


@pytest.mark.asyncio
async def test_safety_check_timeout_fails_closed(monkeypatch):
    class TimeoutLlm:
        async def ainvoke(self, _messages):
            raise TimeoutError

    monkeypatch.setattr("app.core.llm_factory.create_llm", lambda **_kwargs: TimeoutLlm())

    result = await safety_module.safety_check(
        {
            "game_data_sections": {
                "description": "这是一段长度足够的待审查剧本内容，用于确认外部审查超时时不会被静默标记为安全通过。"
                * 2
            }
        }
    )

    assert result["safety_passed"] is False
    assert result["_review_action"] == "regenerate"
    assert "超时" in result["safety_rejection_reason"]
