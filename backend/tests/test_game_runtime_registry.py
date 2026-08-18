import pytest

from app.services.game_runtime import FlowControllerRegistry


@pytest.mark.asyncio
async def test_registry_restores_once_and_remove_is_idempotent():
    registry = FlowControllerRegistry()
    restored = object()
    calls = 0

    async def restore():
        nonlocal calls
        calls += 1
        return restored

    assert await registry.get_or_restore("session", restore) is restored
    assert await registry.get_or_restore("session", restore) is restored
    assert calls == 1

    registry.remove("session")
    registry.remove("session")
    assert registry.get("session") is None
