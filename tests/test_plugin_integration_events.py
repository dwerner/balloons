import asyncio

import pytest

from plugins.integration import load_domain, unload_domain
from plugins.registry import DomainRegistry, set_registry


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


async def _flush_tasks() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_load_domain_emits_via_registry_event_emitter_when_configured():
    manager = _FakeSessionManager()
    registry = DomainRegistry()
    registry.set_event_emitter(manager.emit_domain_event)
    set_registry(registry)

    load_domain("chess")
    try:
        await _flush_tasks()
        assert manager.calls == [
            {
                "domain_id": "system",
                "event_type": "domain_loaded",
                "session_id": "*",
                "data": {"domainId": "chess"},
            }
        ]
    finally:
        unload_domain("chess", emit_event=False)
        set_registry(DomainRegistry())


@pytest.mark.asyncio
async def test_unload_domain_emits_via_registry_event_emitter_when_configured():
    manager = _FakeSessionManager()
    registry = DomainRegistry()
    registry.set_event_emitter(manager.emit_domain_event)
    set_registry(registry)

    load_domain("chess", emit_event=False)
    manager.calls.clear()

    unload_domain("chess")
    await _flush_tasks()

    assert manager.calls == [
        {
            "domain_id": "system",
            "event_type": "domain_unloaded",
            "session_id": "*",
            "data": {"domainId": "chess"},
        }
    ]

    set_registry(DomainRegistry())
