"""WebSocket-exposed service for LSP server management.

Provides UI access to:
- LSP server status (configured and running)
- Start/stop/restart individual servers
- Server health monitoring
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from codegen import ws_service, ws_expose, ws_event, ws_type
from core.debug_log import debug_log, Category


@ws_type
@dataclass
class LSPServerConfig:
    """LSP server configuration for UI."""

    name: str
    command: str
    extensions: list[str]
    languages: list[str]
    idle_timeout_seconds: int


@ws_type
@dataclass
class LSPServerInstance:
    """Running LSP server instance info for UI."""

    key: str  # e.g., "python:/path/to/workspace"
    server_name: str
    workspace: str
    process_id: str
    initialized: bool
    idle_seconds: int
    pending_requests: int
    process_status: str  # "running", "exited", etc.


@ws_type
@dataclass
class LSPStatusResult:
    """Complete LSP status for UI."""

    configured_servers: list[LSPServerConfig]
    running_instances: list[LSPServerInstance]


@ws_type
@dataclass
class LSPActionResult:
    """Result of an LSP action (start/stop/restart)."""

    success: bool
    action: str  # "started", "stopped", "restarted", "already_running", "not_running"
    key: str
    server: str
    workspace: str
    process_id: Optional[str] = None
    error: Optional[str] = None


@ws_type
@dataclass
class LSPDocumentSymbol:
    """A symbol in a document (function, class, etc.)."""

    name: str
    kind: int  # LSP SymbolKind enum
    kind_name: str  # Human-readable kind
    file_path: str
    line_start: int  # 0-indexed
    line_end: int  # 0-indexed
    character_start: int
    character_end: int
    detail: Optional[str] = None
    children: list["LSPDocumentSymbol"] = field(default_factory=list)


@ws_type
@dataclass
class LSPDocumentSymbolsResult:
    """Result of getting document symbols."""

    success: bool
    file_path: str
    symbols: list[LSPDocumentSymbol] = field(default_factory=list)
    error: Optional[str] = None


# LSP SymbolKind enum to human-readable names
LSP_SYMBOL_KINDS = {
    1: "File",
    2: "Module",
    3: "Namespace",
    4: "Package",
    5: "Class",
    6: "Method",
    7: "Property",
    8: "Field",
    9: "Constructor",
    10: "Enum",
    11: "Interface",
    12: "Function",
    13: "Variable",
    14: "Constant",
    15: "String",
    16: "Number",
    17: "Boolean",
    18: "Array",
    19: "Object",
    20: "Key",
    21: "Null",
    22: "EnumMember",
    23: "Struct",
    24: "Event",
    25: "Operator",
    26: "TypeParameter",
}


@ws_service
class LSPService:
    """WebSocket-exposed service for LSP server management."""

    def __init__(self) -> None:
        """Initialize the LSP service."""
        self._event_handlers: list[Callable[[str, dict], None]] = []

    def add_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Register an event handler for WebSocket broadcasting."""
        self._event_handlers.append(handler)

    def remove_event_handler(self, handler: Callable[[str, dict], None]) -> None:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)

    def _emit_event(self, event_name: str, data: dict) -> None:
        """Emit an event to all registered handlers."""
        for handler in self._event_handlers:
            handler(event_name, data)

    @ws_expose
    async def get_status(self) -> LSPStatusResult:
        """Get complete LSP status.

        Returns configured servers and all running instances.
        """
        from supervisor_config import get_supervisor_config
        from core.lsp_client import get_lsp_client
        from core.supervisor_tools import get_supervisor

        config = get_supervisor_config()
        client = get_lsp_client()
        supervisor = get_supervisor()

        # Configured servers
        configured = []
        for server in config.list_lsp_servers():
            configured.append(LSPServerConfig(
                name=server.name,
                command=server.command,
                extensions=server.extensions,
                languages=server.languages,
                idle_timeout_seconds=server.idle_timeout_seconds,
            ))

        # Running instances
        instances = []
        for key, instance in client._instances.items():
            idle_seconds = int(time.time() - instance.last_activity)

            # Get process status
            process_status = "unknown"
            if supervisor:
                try:
                    process_json = await supervisor.get_process(instance.process_id)
                    process = json.loads(process_json)
                    status = process.get("status", {})
                    process_status = status.get("state", "unknown")
                except Exception:
                    pass

            instances.append(LSPServerInstance(
                key=key,
                server_name=instance.server_name,
                workspace=instance.workspace_root,
                process_id=instance.process_id,
                initialized=instance.initialized,
                idle_seconds=idle_seconds,
                pending_requests=len(instance.pending_requests),
                process_status=process_status,
            ))

        return LSPStatusResult(
            configured_servers=configured,
            running_instances=instances,
        )

    @ws_expose
    async def start_server(
        self,
        language: str,
        workspace: Optional[str] = None,
    ) -> LSPActionResult:
        """Start an LSP server.

        Args:
            language: Language server name (e.g., "python")
            workspace: Workspace root (defaults to cwd)

        Returns:
            Action result with status
        """
        from core.lsp_client import get_lsp_client
        import os

        workspace = workspace or os.getcwd()
        workspace = str(Path(workspace).resolve())

        client = get_lsp_client()
        key = client._instance_key(language, workspace)

        # Check if already running
        if key in client._instances:
            return LSPActionResult(
                success=True,
                action="already_running",
                key=key,
                server=language,
                workspace=workspace,
                process_id=client._instances[key].process_id,
            )

        # Start the server
        try:
            instance = await client.ensure_server(language, workspace)
            if instance:
                self._emit_event("lspServerStarted", {
                    "key": key,
                    "server": language,
                    "workspace": workspace,
                    "processId": instance.process_id,
                })

                return LSPActionResult(
                    success=True,
                    action="started",
                    key=key,
                    server=language,
                    workspace=workspace,
                    process_id=instance.process_id,
                )
            else:
                return LSPActionResult(
                    success=False,
                    action="started",
                    key=key,
                    server=language,
                    workspace=workspace,
                    error="Failed to start server",
                )
        except Exception as e:
            return LSPActionResult(
                success=False,
                action="started",
                key=key,
                server=language,
                workspace=workspace,
                error=str(e),
            )

    @ws_expose
    async def stop_server(
        self,
        language: Optional[str] = None,
        workspace: Optional[str] = None,
        key: Optional[str] = None,
    ) -> LSPActionResult:
        """Stop an LSP server.

        Can specify by language+workspace or by key.

        Args:
            language: Language server name
            workspace: Workspace root
            key: Instance key (alternative to language+workspace)

        Returns:
            Action result with status
        """
        from core.lsp_client import get_lsp_client
        import os

        # Parse key if provided
        if key:
            parts = key.split(":", 1)
            if len(parts) == 2:
                language, workspace = parts

        if not language:
            return LSPActionResult(
                success=False,
                action="stopped",
                key=key or "",
                server=language or "",
                workspace=workspace or "",
                error="language or key is required",
            )

        workspace = workspace or os.getcwd()
        workspace = str(Path(workspace).resolve())

        client = get_lsp_client()
        key = client._instance_key(language, workspace)

        if key not in client._instances:
            return LSPActionResult(
                success=True,
                action="not_running",
                key=key,
                server=language,
                workspace=workspace,
            )

        process_id = client._instances[key].process_id

        try:
            success = await client.stop_server(language, workspace)
            if success:
                self._emit_event("lspServerStopped", {
                    "key": key,
                    "server": language,
                    "workspace": workspace,
                    "processId": process_id,
                })

                return LSPActionResult(
                    success=True,
                    action="stopped",
                    key=key,
                    server=language,
                    workspace=workspace,
                    process_id=process_id,
                )
            else:
                return LSPActionResult(
                    success=False,
                    action="stopped",
                    key=key,
                    server=language,
                    workspace=workspace,
                    error="Failed to stop server",
                )
        except Exception as e:
            return LSPActionResult(
                success=False,
                action="stopped",
                key=key,
                server=language,
                workspace=workspace,
                error=str(e),
            )

    @ws_expose
    async def restart_server(
        self,
        language: Optional[str] = None,
        workspace: Optional[str] = None,
        key: Optional[str] = None,
    ) -> LSPActionResult:
        """Restart an LSP server.

        Args:
            language: Language server name
            workspace: Workspace root
            key: Instance key (alternative to language+workspace)

        Returns:
            Action result with status
        """
        from core.lsp_client import get_lsp_client
        import os

        # Parse key if provided
        if key:
            parts = key.split(":", 1)
            if len(parts) == 2:
                language, workspace = parts

        if not language:
            return LSPActionResult(
                success=False,
                action="restarted",
                key=key or "",
                server=language or "",
                workspace=workspace or "",
                error="language or key is required",
            )

        workspace = workspace or os.getcwd()
        workspace = str(Path(workspace).resolve())

        client = get_lsp_client()
        key = client._instance_key(language, workspace)

        was_running = key in client._instances

        # Stop if running
        if was_running:
            await client.stop_server(language, workspace)

        # Start fresh
        try:
            instance = await client.ensure_server(language, workspace)
            if instance:
                self._emit_event("lspServerRestarted", {
                    "key": key,
                    "server": language,
                    "workspace": workspace,
                    "processId": instance.process_id,
                    "wasRunning": was_running,
                })

                return LSPActionResult(
                    success=True,
                    action="restarted" if was_running else "started",
                    key=key,
                    server=language,
                    workspace=workspace,
                    process_id=instance.process_id,
                )
            else:
                return LSPActionResult(
                    success=False,
                    action="restarted",
                    key=key,
                    server=language,
                    workspace=workspace,
                    error="Failed to start server",
                )
        except Exception as e:
            return LSPActionResult(
                success=False,
                action="restarted",
                key=key,
                server=language,
                workspace=workspace,
                error=str(e),
            )

    @ws_expose
    async def stop_all_servers(self) -> int:
        """Stop all running LSP servers.

        Returns:
            Number of servers stopped
        """
        from core.lsp_client import get_lsp_client

        client = get_lsp_client()
        count = await client.stop_all_servers()

        if count > 0:
            self._emit_event("lspAllServersStopped", {"count": count})

        return count

    @ws_expose
    async def get_document_symbols(
        self,
        file_path: str,
    ) -> LSPDocumentSymbolsResult:
        """Get all symbols in a document.

        Uses the LSP textDocument/documentSymbol request.
        The language server is automatically started if needed.

        Args:
            file_path: Absolute path to the file

        Returns:
            List of document symbols (hierarchical)
        """
        from core.lsp_client import get_lsp_client

        client = get_lsp_client()

        try:
            raw_symbols = await client.get_document_symbols(file_path)

            if raw_symbols is None:
                return LSPDocumentSymbolsResult(
                    success=False,
                    file_path=file_path,
                    error="No LSP server available for this file type",
                )

            # Convert to our type
            symbols = self._convert_symbols(raw_symbols, file_path)

            return LSPDocumentSymbolsResult(
                success=True,
                file_path=file_path,
                symbols=symbols,
            )

        except Exception as e:
            debug_log.error(
                f"Failed to get document symbols: {e}",
                category=Category.SUPERVISOR,
            )
            return LSPDocumentSymbolsResult(
                success=False,
                file_path=file_path,
                error=str(e),
            )

    def _convert_symbols(
        self,
        raw_symbols: list,
        file_path: str,
    ) -> list[LSPDocumentSymbol]:
        """Convert LSP symbols to our type.

        Handles both DocumentSymbol (hierarchical) and SymbolInformation (flat) formats.
        """
        symbols = []

        for raw in raw_symbols:
            # DocumentSymbol has 'range', SymbolInformation has 'location'
            if "range" in raw:
                # DocumentSymbol format (hierarchical)
                rng = raw["range"]
                start = rng["start"]
                end = rng["end"]

                kind = raw.get("kind", 0)
                kind_name = LSP_SYMBOL_KINDS.get(kind, "Unknown")

                children = []
                if "children" in raw:
                    children = self._convert_symbols(raw["children"], file_path)

                symbols.append(LSPDocumentSymbol(
                    name=raw.get("name", ""),
                    kind=kind,
                    kind_name=kind_name,
                    file_path=file_path,
                    line_start=start.get("line", 0),
                    line_end=end.get("line", 0),
                    character_start=start.get("character", 0),
                    character_end=end.get("character", 0),
                    detail=raw.get("detail"),
                    children=children,
                ))

            elif "location" in raw:
                # SymbolInformation format (flat)
                loc = raw["location"]
                rng = loc.get("range", {})
                start = rng.get("start", {})
                end = rng.get("end", {})

                kind = raw.get("kind", 0)
                kind_name = LSP_SYMBOL_KINDS.get(kind, "Unknown")

                # Extract file path from URI
                uri = loc.get("uri", "")
                symbol_file = uri.replace("file://", "") if uri.startswith("file://") else file_path

                symbols.append(LSPDocumentSymbol(
                    name=raw.get("name", ""),
                    kind=kind,
                    kind_name=kind_name,
                    file_path=symbol_file,
                    line_start=start.get("line", 0),
                    line_end=end.get("line", 0),
                    character_start=start.get("character", 0),
                    character_end=end.get("character", 0),
                    detail=raw.get("containerName"),
                    children=[],
                ))

        return symbols

    # Events
    @ws_event
    def lsp_server_started(self, data: dict) -> dict:
        """Fired when an LSP server starts."""
        pass

    @ws_event
    def lsp_server_stopped(self, data: dict) -> dict:
        """Fired when an LSP server stops."""
        pass

    @ws_event
    def lsp_server_restarted(self, data: dict) -> dict:
        """Fired when an LSP server restarts."""
        pass
