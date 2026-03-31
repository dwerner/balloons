import pytest

from plugins.base import DomainEvent, ToolResult
from plugins.rpc_service import DomainRpcService


class _FakeSession:
    id = "session-123"


class _FakeInnerManager:
    def get_session(self, session_id: str):
        if session_id == "session-123":
            return _FakeSession()
        return None


class _FakeManager:
    def __init__(self):
        self._manager = _FakeInnerManager()


class _FakeEventEmitter:
    def __init__(self):
        self.calls = []

    async def __call__(self, domain_id: str, event_type: str, session_id: str, data: dict):
        self.calls.append(
            {
                "domain_id": domain_id,
                "event_type": event_type,
                "session_id": session_id,
                "data": data,
            }
        )


class _FakeDomain:
    async def method(self, session=None):
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
async def test_call_domain_method_emits_events_via_injected_emitter():
    service = DomainRpcService()
    service.set_manager(_FakeManager())
    emitter = _FakeEventEmitter()
    service.set_event_emitter(emitter)
    service._domain_methods["fakeMethod"] = (_FakeDomain(), "method", "fake")

    result = await service.call_domain_method("fakeMethod", "session-123", {})

    assert result == {"result": "ok"}
    assert emitter.calls == [
        {
            "domain_id": "fake",
            "event_type": "fake.event",
            "session_id": "session-123",
            "data": {"ok": True},
        }
    ]


@pytest.mark.asyncio
async def test_call_domain_method_prefers_event_target_session_when_present():
    class _TargetedDomain:
        async def method(self, session=None):
            return ToolResult(
                result="ok",
                is_error=False,
                events=[
                    DomainEvent(
                        type="fake.event",
                        source_domain="fake",
                        target_session="target-999",
                        payload={"ok": True},
                    )
                ],
            )

    service = DomainRpcService()
    service.set_manager(_FakeManager())
    emitter = _FakeEventEmitter()
    service.set_event_emitter(emitter)
    service._domain_methods["fakeMethod"] = (_TargetedDomain(), "method", "fake")

    result = await service.call_domain_method("fakeMethod", "session-123", {})

    assert result == {"result": "ok"}
    assert emitter.calls == [
        {
            "domain_id": "fake",
            "event_type": "fake.event",
            "session_id": "target-999",
            "data": {"ok": True},
        }
    ]
