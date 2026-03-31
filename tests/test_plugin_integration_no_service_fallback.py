import asyncio
import builtins

import pytest

from plugins.integration import load_domain, unload_domain
from plugins.registry import DomainRegistry, set_registry


async def _flush_tasks() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_load_domain_without_event_emitter_does_not_import_service(monkeypatch):
    set_registry(DomainRegistry())

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "service":
            raise AssertionError("integration should not import service when no event emitter is configured")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    load_domain("chess")
    try:
        await _flush_tasks()
    finally:
        unload_domain("chess", emit_event=False)
        set_registry(DomainRegistry())
