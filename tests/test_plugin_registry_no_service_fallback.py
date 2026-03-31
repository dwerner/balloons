import builtins

import pytest

from plugins.base import DomainEvent, ToolResult
from plugins.registry import DomainRegistry


class _FakeSession:
    id = "session-123"


class _FakeEventDomain:
    async def handle_tool(self, tool_name, params, session):
        return ToolResult(
            result="ok",
            is_error=False,
            events=[
                DomainEvent(
                    type="fake.event",
                    source_domain="fake",
                    target_session=None,
                    payload={"ok": True},
                )
            ],
        )


@pytest.mark.asyncio
async def test_registry_without_event_emitter_silently_skips_event_forwarding(monkeypatch):
    registry = DomainRegistry()
    registry._domains["fake"] = _FakeEventDomain()
    registry._tool_to_domain["fake_tool"] = "fake"

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "service":
            raise AssertionError("registry should not import service when no event emitter is configured")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    result, is_error = await registry.execute_tool_as_provider("fake_tool", {}, _FakeSession(), "/tmp")

    assert result == "ok"
    assert is_error is False
