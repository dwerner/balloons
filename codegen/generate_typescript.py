#!/usr/bin/env python3
"""Generate TypeScript types and client code from Python @ws_expose decorators.

Usage:
    python -m codegen.generate_typescript

This generates:
    web/generated/types.ts      - TypeScript interfaces for exposed types
    web/generated/client.ts     - TypeScript client for WebSocket RPC

The generated code is committed to the repo. If the Python API changes,
re-run this generator and commit the updated TypeScript code.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from codegen.ws_expose import (
    WsExposeRegistry,
    ServiceSpec,
    MethodSpec,
    EventSpec,
    python_to_ts_type,
    generate_ts_interface,
    to_camel_case,
)


def get_ts_output_dir() -> Path:
    """Get the path to the TypeScript generated directory."""
    return project_root / "web" / "generated"


def generate_types_header() -> str:
    """Generate the types.ts file header."""
    return f'''// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_type decorators.
//
// To regenerate:
//     python -m codegen.generate_typescript
//
// To add new types, add @ws_type decorator to dataclasses in your service modules.

'''


def generate_types_file() -> str:
    """Generate the types.ts content."""
    parts = [generate_types_header()]

    types = WsExposeRegistry.get_types()
    if not types:
        parts.append("// No types registered with @ws_type\n")
        return "".join(parts)

    for type_cls in types:
        parts.append(generate_ts_interface(type_cls))
        parts.append("\n\n")

    return "".join(parts)


def generate_client_header() -> str:
    """Generate the client.ts file header."""
    return f'''// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_event decorators.
//
// To regenerate:
//     python -m codegen.generate_typescript
//
// To add new methods/events, add @ws_expose/@ws_event decorators in service modules.

import type * as Types from './types';

// Simple request ID generator for JSON-RPC correlation
let _requestId = 0;
function generateRequestId(): string {{
  return String(++_requestId);
}}

'''


def _prefix_custom_types(ts_type: str, registered_types: set[str]) -> str:
    """Add Types. prefix to custom types that are in the types.ts file."""
    # Simple types that should not be prefixed
    simple_types = {"string", "number", "boolean", "null", "void", "unknown"}

    # Handle arrays
    if ts_type.endswith("[]"):
        inner = ts_type[:-2]
        return f"{_prefix_custom_types(inner, registered_types)}[]"

    # Handle unions
    if " | " in ts_type:
        parts = ts_type.split(" | ")
        return " | ".join(_prefix_custom_types(p.strip(), registered_types) for p in parts)

    # Handle tuples
    if ts_type.startswith("[") and ts_type.endswith("]"):
        inner = ts_type[1:-1]
        parts = inner.split(", ")
        return "[" + ", ".join(_prefix_custom_types(p.strip(), registered_types) for p in parts) + "]"

    # Handle Record<K, V>
    if ts_type.startswith("Record<"):
        # Extract contents between < and >
        inner = ts_type[7:-1]
        # Split on first comma
        comma_idx = inner.find(", ")
        if comma_idx > 0:
            key = inner[:comma_idx]
            val = inner[comma_idx + 2:]
            return f"Record<{_prefix_custom_types(key, registered_types)}, {_prefix_custom_types(val, registered_types)}>"
        return ts_type

    # Handle Promise<T>
    if ts_type.startswith("Promise<"):
        inner = ts_type[8:-1]
        return f"Promise<{_prefix_custom_types(inner, registered_types)}>"

    # Check if this is a registered custom type
    if ts_type in registered_types:
        return f"Types.{ts_type}"

    return ts_type


def generate_method_signature(method: MethodSpec, registered_types: set[str] = None) -> str:
    """Generate TypeScript method signature."""
    registered_types = registered_types or set()

    params = []
    for p in method.params:
        ts_type = python_to_ts_type(p.type_hint)
        ts_type = _prefix_custom_types(ts_type, registered_types)
        optional = "?" if not p.required else ""
        params.append(f"{p.wire_name}{optional}: {ts_type}")

    return_type = python_to_ts_type(method.return_type) if method.return_type else "void"
    return_type = _prefix_custom_types(return_type, registered_types)
    params_str = ", ".join(params)

    return f"{method.wire_name}({params_str}): Promise<{return_type}>"


def generate_event_signature(event: EventSpec, registered_types: set[str] = None) -> str:
    """Generate TypeScript event subscription signature."""
    registered_types = registered_types or set()
    payload_type = python_to_ts_type(event.payload_type) if event.payload_type else "unknown"
    payload_type = _prefix_custom_types(payload_type, registered_types)
    return f"{event.wire_name}(callback: (data: {payload_type}) => void): Unsubscribe"


def generate_service_interface(service: ServiceSpec, registered_types: set[str] = None) -> str:
    """Generate TypeScript interface for a service."""
    registered_types = registered_types or set()
    lines = []

    # Add JSDoc
    if service.docstring:
        lines.append("/**")
        for line in service.docstring.strip().split("\n"):
            lines.append(f" * {line.strip()}")
        lines.append(" */")

    # Remove redundant "Service" if wire_name already ends with it
    interface_name = service.wire_name
    if not interface_name.endswith("Service"):
        interface_name = f"{interface_name}Service"
    lines.append(f"export interface {interface_name} {{")

    # Methods
    for method in service.methods:
        # Add method JSDoc
        if method.docstring:
            lines.append("  /**")
            for line in method.docstring.strip().split("\n"):
                lines.append(f"   * {line.strip()}")
            lines.append("   */")
        lines.append(f"  {generate_method_signature(method, registered_types)};")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def generate_events_interface(service: ServiceSpec, registered_types: set[str] = None) -> str:
    """Generate TypeScript interface for service events."""
    if not service.events:
        return ""

    registered_types = registered_types or set()

    # Remove redundant "Service" suffix if present
    base_name = service.wire_name
    if base_name.endswith("Service"):
        base_name = base_name[:-7]  # Remove "Service"

    lines = []
    lines.append(f"export interface {base_name}Events {{")

    for event in service.events:
        if event.docstring:
            lines.append("  /**")
            for line in event.docstring.strip().split("\n"):
                lines.append(f"   * {line.strip()}")
            lines.append("   */")
        lines.append(f"  {generate_event_signature(event, registered_types)};")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def generate_client_class(service: ServiceSpec, registered_types: set[str] = None) -> str:
    """Generate TypeScript client class for a service."""
    registered_types = registered_types or set()
    lines = []

    # Compute interface name (same logic as generate_service_interface)
    interface_name = service.wire_name
    if not interface_name.endswith("Service"):
        interface_name = f"{interface_name}Service"

    lines.append(f"export class {service.wire_name}Client implements {interface_name} {{")
    lines.append("  private ws: WebSocket;")
    lines.append("  private pending: Map<string, { resolve: (v: any) => void; reject: (e: Error) => void }> = new Map();")
    lines.append("  private eventHandlers: Map<string, Set<(data: any) => void>> = new Map();")
    lines.append("")

    # Constructor
    lines.append("  constructor(ws: WebSocket) {")
    lines.append("    this.ws = ws;")
    lines.append("    this.ws.addEventListener('message', this.handleMessage.bind(this));")
    lines.append("  }")
    lines.append("")

    # Message handler
    lines.append("  private handleMessage(event: MessageEvent): void {")
    lines.append("    const msg = JSON.parse(event.data);")
    lines.append("    if (msg.id && this.pending.has(msg.id)) {")
    lines.append("      const { resolve, reject } = this.pending.get(msg.id)!;")
    lines.append("      this.pending.delete(msg.id);")
    lines.append("      if (msg.error) {")
    lines.append("        reject(new Error(msg.error.message));")
    lines.append("      } else {")
    lines.append("        resolve(msg.result);")
    lines.append("      }")
    lines.append("    } else if (msg.event) {")
    lines.append("      const handlers = this.eventHandlers.get(msg.event);")
    lines.append("      if (handlers) {")
    lines.append("        handlers.forEach(h => h(msg.data));")
    lines.append("      }")
    lines.append("    }")
    lines.append("  }")
    lines.append("")

    # Call helper
    lines.append("  private async call<T>(method: string, params: Record<string, unknown>): Promise<T> {")
    lines.append("    const id = generateRequestId();")
    lines.append("    return new Promise((resolve, reject) => {")
    lines.append("      this.pending.set(id, { resolve, reject });")
    lines.append("      this.ws.send(JSON.stringify({ id, method, params }));")
    lines.append("    });")
    lines.append("  }")
    lines.append("")

    # Subscribe helper
    lines.append("  private subscribe(event: string, callback: (data: any) => void): Unsubscribe {")
    lines.append("    if (!this.eventHandlers.has(event)) {")
    lines.append("      this.eventHandlers.set(event, new Set());")
    lines.append("    }")
    lines.append("    this.eventHandlers.get(event)!.add(callback);")
    lines.append("    return () => {")
    lines.append("      this.eventHandlers.get(event)?.delete(callback);")
    lines.append("    };")
    lines.append("  }")
    lines.append("")

    # Generate method implementations
    for method in service.methods:
        params = []
        call_params = []
        for p in method.params:
            ts_type = python_to_ts_type(p.type_hint)
            ts_type = _prefix_custom_types(ts_type, registered_types)
            optional = "?" if not p.required else ""
            params.append(f"{p.wire_name}{optional}: {ts_type}")
            call_params.append(f"{p.wire_name}")

        return_type = python_to_ts_type(method.return_type) if method.return_type else "void"
        return_type = _prefix_custom_types(return_type, registered_types)
        params_str = ", ".join(params)
        call_params_str = ", ".join(f"{p}: {p}" for p in call_params)

        lines.append(f"  async {method.wire_name}({params_str}): Promise<{return_type}> {{")
        # Call the qualified method name ("<ServiceName>.<method>") so dispatch
        # is unambiguous even when multiple services expose a same-named method
        # (see ws_server._qualified_dispatch). Fixes BUGS.md #11.
        lines.append(f"    return this.call('{service.name}.{method.wire_name}', {{ {call_params_str} }});")
        lines.append("  }")
        lines.append("")

    # Generate event subscriptions
    for event in service.events:
        payload_type = python_to_ts_type(event.payload_type) if event.payload_type else "unknown"
        payload_type = _prefix_custom_types(payload_type, registered_types)
        # The method name is e.g. "onTurnStarted" but the wire protocol event name is "turnStarted"
        # Strip the "on" prefix and lowercase the first char to match the server's event names
        subscribe_name = event.wire_name
        if subscribe_name.startswith("on") and len(subscribe_name) > 2:
            subscribe_name = subscribe_name[2].lower() + subscribe_name[3:]
        lines.append(f"  {event.wire_name}(callback: (data: {payload_type}) => void): Unsubscribe {{")
        lines.append(f"    return this.subscribe('{subscribe_name}', callback);")
        lines.append("  }")
        lines.append("")

    lines.append("}")
    return "\n".join(lines)


def generate_client_file() -> str:
    """Generate the client.ts content."""
    parts = [generate_client_header()]

    # Add Unsubscribe type
    parts.append("export type Unsubscribe = () => void;\n\n")

    services = WsExposeRegistry.get_services()
    if not services:
        parts.append("// No services registered with @ws_service\n")
        return "".join(parts)

    # Collect all registered type names for prefixing
    registered_types = {t.__name__ for t in WsExposeRegistry.get_types()}

    for service in services.values():
        # Service interface
        parts.append(generate_service_interface(service, registered_types))
        parts.append("\n\n")

        # Events interface (if any events)
        events_interface = generate_events_interface(service, registered_types)
        if events_interface:
            parts.append(events_interface)
            parts.append("\n\n")

        # Client class
        parts.append(generate_client_class(service, registered_types))
        parts.append("\n\n")

    return "".join(parts)


def main():
    """Generate TypeScript code from registered Python schemas."""
    # Import modules containing @ws_service decorated classes
    # Add imports here for any module with services to export to TypeScript
    modules_to_import = [
        ("service.queue_state_service", "QueueStateService"),
        ("service.session_manager_service", "SessionManagerService"),
        ("service.task_state_service", "TaskStateService"),
        ("service.session_data_service", "SessionDataService"),
        ("service.image_service", "ImageService"),
        ("service.file_state_service", "FileStateService"),
        ("service.debug_log_service", "DebugLogService"),
        ("service.traffic_capture_service", "TrafficCaptureService"),
        ("service.sound_service", "SoundService"),
        ("service.supervisor_state_service", "SupervisorStateService"),
        ("service.browser_state_service", "BrowserStateService"),
        ("service.lsp_service", "LSPService"),
        ("plugins.rpc_service", "DomainRpcService"),
    ]

    for module_name, label in modules_to_import:
        try:
            __import__(module_name)
        except ImportError as e:
            print(f"Warning: Could not import {label} from {module_name}: {e}")

    services = WsExposeRegistry.get_services()
    types = WsExposeRegistry.get_types()

    print(f"Generating TypeScript code:")
    print(f"  - {len(services)} services")
    print(f"  - {len(types)} types")

    for name, service in services.items():
        print(f"  Service: {name}")
        for method in service.methods:
            print(f"    - {method.wire_name}()")
        for event in service.events:
            print(f"    - {event.wire_name} (event)")

    # Ensure output directory exists
    output_dir = get_ts_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate types.ts
    types_path = output_dir / "types.ts"
    types_content = generate_types_file()
    types_path.write_text(types_content)
    print(f"\nGenerated: {types_path}")

    # Generate client.ts
    client_path = output_dir / "client.ts"
    client_content = generate_client_file()
    client_path.write_text(client_content)
    print(f"Generated: {client_path}")

    print("\nDone! Run 'npx tsc --noEmit' to verify the generated code.")


if __name__ == "__main__":
    main()
