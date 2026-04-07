# Workstream 3: Service Locator Inventory and Completion Notes

## Goal
Remove the global session-manager locator from the active plugin/runtime eventing path by replacing it with explicit dependency wiring, while preserving compatibility exports until import-surface cleanup decides whether to remove them.

## Original session-manager locator sites

### Definitions
- `service/__init__.py`
  - `get_session_manager_service()`
  - `set_session_manager_service()`

### Startup wiring
- `headless.py`
  - previously called `set_session_manager_service(session_service)`
  - now replaced with explicit event-emitter wiring

### Plugin/runtime call sites
- `plugins/integration.py`
  - previously imported `get_session_manager_service()` for domain load/unload events
  - now uses the registry event emitter only
- `plugins/registry.py`
  - previously fell back to `get_session_manager_service()` for ToolResult event forwarding
  - now uses the configured event emitter only
- `plugins/rpc_service.py`
  - previously imported `get_session_manager_service()` for RPC event forwarding
  - now uses injected event emitter only

## Current state

### Main runtime path
The headless runtime now wires plugin event emission explicitly:
- `get_registry().set_event_emitter(session_service.emit_domain_event)`
- `domain_rpc_service.set_event_emitter(session_service.emit_domain_event)`

The service locator is no longer part of the runtime event flow.

### Remaining legacy surface
The locator definitions remain exported from `service/__init__.py` for compatibility:
- `get_session_manager_service`
- `set_session_manager_service`

These symbols are now documented as legacy/deprecated compatibility exports. At the time of this note, no in-repo runtime caller still uses them.

## Validation added in this fork
- `tests/test_plugin_integration_events.py`
- `tests/test_plugin_registry_event_emitter.py`
- `tests/test_plugin_registry_no_service_fallback.py`
- `tests/test_plugin_integration_no_service_fallback.py`
- `tests/test_domain_rpc_service_events.py`
- `tests/test_service_locator_legacy_exports.py`
- `tests/test_no_runtime_service_locator_usage.py`

## Completion criteria met
- Runtime startup no longer registers the session manager in a global locator.
- Plugin integration event emission uses explicit registry wiring.
- Plugin registry event forwarding uses explicit emitter wiring.
- Domain RPC event forwarding uses explicit emitter wiring.
- Repo-level test coverage confirms no in-repo runtime caller still uses the locator.
- Legacy exports remain available for compatibility, but are no longer part of the active runtime design.

## Follow-up
If Workstream 2 decides the public `service` import surface may change, the legacy locator exports can be removed in a later compatibility cleanup. Until then, keeping them as deprecated compatibility exports avoids mixing WS3 runtime cleanup with WS2 import-contract decisions.
