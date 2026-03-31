import pytest

from plugins.base import DomainEvent, ToolResult
from plugins.registry import DomainRegistry


class _FakeSession:
    id = "session-123"


class _FakeSessionManager:
    def __init__(self):
        self.calls = []

    async def emit_domain_event(self, domain_id: str, event_type: str, session_id: str, data: dict):
        self.calls.append(
            {
                "domain_id": domain_id,
                "event_type": event_type,
                "session_id": session_id,
                "data": data,
            }
        )


class _FakeEventDomain:
    id = "fake"

    async def handle_tool(self, tool_name, params, session):
        return ToolResult(
            result="ok",
            is_error=False,
            events=[
                DomainEvent(
                    type="fake.event",
                    source_domain="fake",
                    target_session=params.get("target_session"),
                    payload={"ok": True},
                )
            ],
        )


@pytest.mark.asyncio
async def test_execute_tool_as_provider_uses_injected_event_emitter_without_service_imports():
    manager = _FakeSessionManager()
    registry = DomainRegistry(event_emitter=manager.emit_domain_event)
    registry._domains["fake"] = _FakeEventDomain()
    registry._tool_to_domain["fake_tool"] = "fake"

    result, is_error = await registry.execute_tool_as_provider(
        "fake_tool",
        {},
        _FakeSession(),
        "/tmp",
    )

    assert result == "ok"
    assert is_error is False
    assert manager.calls == [
        {
            "domain_id": "fake",
            "event_type": "fake.event",
            "session_id": "session-123",
            "data": {"ok": True},
        }
    ]


@pytest.mark.asyncio
async def test_execute_tool_as_provider_prefers_event_target_session_when_present():
    manager = _FakeSessionManager()
    registry = DomainRegistry(event_emitter=manager.emit_domain_event)
    registry._domains["fake"] = _FakeEventDomain()
    registry._tool_to_domain["fake_tool"] = "fake"

    await registry.execute_tool_as_provider(
        "fake_tool",
        {"target_session": "target-999"},
        _FakeSession(),
        "/tmp",
    )

    assert manager.calls == [
        {
            "domain_id": "fake",
            "event_type": "fake.event",
            "session_id": "target-999",
            "data": {"ok": True},
        }
    ]
