"""LSP client built on the supervisor system.

LSP servers are supervised processes that communicate via JSON-RPC over stdin/stdout.
This module adds the LSP protocol layer on top of the existing supervisor infrastructure.

Key features:
- Automatic server lifecycle management (start on demand, stop on idle)
- JSON-RPC message framing with Content-Length headers
- Request/response correlation
- Caching of frequently-used results
- Workspace-aware server instances
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING
from collections import OrderedDict

from .debug_log import debug_log, Category

if TYPE_CHECKING:
    from supervisor_config import LSPServerConfig


# LSP message IDs - start high to avoid conflicts
_next_request_id = 100000


def _get_next_request_id() -> int:
    """Get the next unique request ID."""
    global _next_request_id
    _next_request_id += 1
    return _next_request_id


@dataclass
class LSPServerInstance:
    """A running LSP server instance.

    Attributes:
        server_name: Name of the server config (e.g., "python")
        process_id: Supervisor process ID
        workspace_root: Root directory for this workspace
        initialized: Whether LSP initialization has completed
        capabilities: Server capabilities from initialize response
        last_activity: Timestamp of last request/response
        pending_requests: Map of request ID to asyncio.Future
    """

    server_name: str
    process_id: str
    workspace_root: str
    initialized: bool = False
    capabilities: dict = field(default_factory=dict)
    last_activity: float = field(default_factory=time.time)
    pending_requests: dict[int, asyncio.Future] = field(default_factory=dict)


class LSPResponseCache:
    """LRU cache for LSP responses.

    Caches responses that are unlikely to change frequently, like
    document symbols, type definitions, etc.
    """

    def __init__(self, max_size: int = 1000):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl_seconds = 60.0  # Default TTL

    def get(self, key: str) -> Optional[Any]:
        """Get a cached value if it exists and hasn't expired."""
        if key not in self._cache:
            return None

        value, timestamp = self._cache[key]
        if time.time() - timestamp > self._ttl_seconds:
            del self._cache[key]
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Cache a value with optional custom TTL."""
        if len(self._cache) >= self._max_size:
            # Remove oldest
            self._cache.popitem(last=False)

        self._cache[key] = (value, time.time())

    def invalidate_file(self, file_path: str) -> None:
        """Invalidate all cache entries for a file."""
        to_remove = [k for k in self._cache if file_path in k]
        for k in to_remove:
            del self._cache[k]

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()


class LSPClient:
    """LSP client that manages language server instances via the supervisor.

    This is a singleton that manages all LSP server instances. It:
    - Starts servers on demand when files are opened
    - Routes requests to the appropriate server based on file type
    - Handles JSON-RPC message framing
    - Correlates requests with responses
    - Caches frequently-used results
    """

    def __init__(self):
        self._instances: dict[str, LSPServerInstance] = {}  # key: f"{server_name}:{workspace_root}"
        self._cache = LSPResponseCache()
        self._lock = asyncio.Lock()
        self._output_handlers: dict[str, asyncio.Task] = {}

    def _instance_key(self, server_name: str, workspace_root: str) -> str:
        """Generate a unique key for a server instance."""
        return f"{server_name}:{workspace_root}"

    async def ensure_server(
        self,
        server_name: str,
        workspace_root: str,
    ) -> Optional[LSPServerInstance]:
        """Ensure an LSP server is running for the given workspace.

        Starts the server if needed and waits for initialization.

        Args:
            server_name: Name of the LSP server (e.g., "python")
            workspace_root: Root directory of the workspace

        Returns:
            LSPServerInstance if successful, None otherwise
        """
        from supervisor_config import get_supervisor_config
        from .supervisor_tools import get_supervisor

        key = self._instance_key(server_name, workspace_root)

        async with self._lock:
            # Check if already running
            if key in self._instances:
                instance = self._instances[key]
                instance.last_activity = time.time()
                return instance

            # Get server config
            config = get_supervisor_config()
            server_config = config.get_lsp_server(server_name)
            if not server_config:
                debug_log.error(
                    f"LSP server not found: {server_name}",
                    category=Category.SUPERVISOR,
                )
                return None

            # Start the server via supervisor
            supervisor = get_supervisor()
            if not supervisor:
                debug_log.error(
                    "Supervisor not initialized",
                    category=Category.SUPERVISOR,
                )
                return None

            try:
                process_id = supervisor.start(
                    command=server_config.command,
                    session_id="__lsp__",  # Special session for LSP servers
                    working_dir=workspace_root,
                    name=f"lsp:{server_name}:{Path(workspace_root).name}",
                    env_json=None,
                    mode="lsp",  # Use Content-Length framing
                )

                debug_log.info(
                    f"Started LSP server: {server_name}",
                    category=Category.SUPERVISOR,
                    details={
                        "process_id": process_id[:8],
                        "workspace": workspace_root,
                    },
                )

                instance = LSPServerInstance(
                    server_name=server_name,
                    process_id=process_id,
                    workspace_root=workspace_root,
                )
                self._instances[key] = instance

                # Start output handler for this server
                self._output_handlers[key] = asyncio.create_task(
                    self._handle_server_output(instance)
                )

                # Initialize the server
                await self._initialize_server(instance, server_config)

                return instance

            except Exception as e:
                debug_log.error(
                    f"Failed to start LSP server: {e}",
                    category=Category.SUPERVISOR,
                )
                return None

    async def _initialize_server(
        self,
        instance: LSPServerInstance,
        config: "LSPServerConfig",
    ) -> bool:
        """Send the LSP initialize request and wait for response.

        Args:
            instance: The server instance
            config: Server configuration

        Returns:
            True if initialization succeeded
        """
        init_params = {
            "processId": None,  # We're not providing a parent process
            "rootUri": f"file://{instance.workspace_root}",
            "rootPath": instance.workspace_root,
            "capabilities": {
                "textDocument": {
                    "completion": {
                        "completionItem": {
                            "snippetSupport": False,
                            "documentationFormat": ["plaintext", "markdown"],
                        }
                    },
                    "hover": {
                        "contentFormat": ["plaintext", "markdown"],
                    },
                    "definition": {},
                    "references": {},
                    "documentSymbol": {
                        "hierarchicalDocumentSymbolSupport": True,
                    },
                    "typeDefinition": {},
                    "implementation": {},
                    "codeAction": {},
                    "diagnostic": {},
                },
                "workspace": {
                    "workspaceFolders": True,
                    "symbol": {},
                },
            },
            "workspaceFolders": [
                {
                    "uri": f"file://{instance.workspace_root}",
                    "name": Path(instance.workspace_root).name,
                }
            ],
        }

        # Add any custom initialization options
        if config.initialization_options:
            init_params["initializationOptions"] = config.initialization_options

        try:
            response = await self._send_request(
                instance,
                "initialize",
                init_params,
                timeout=30.0,
            )

            if response and "capabilities" in response:
                instance.capabilities = response["capabilities"]
                instance.initialized = True

                # Send initialized notification
                await self._send_notification(instance, "initialized", {})

                debug_log.info(
                    f"LSP server initialized: {instance.server_name}",
                    category=Category.SUPERVISOR,
                    details={"capabilities": list(instance.capabilities.keys())},
                )
                return True

        except Exception as e:
            debug_log.error(
                f"LSP initialization failed: {e}",
                category=Category.SUPERVISOR,
            )

        return False

    async def _send_request(
        self,
        instance: LSPServerInstance,
        method: str,
        params: dict,
        timeout: float = 10.0,
    ) -> Optional[dict]:
        """Send a JSON-RPC request and wait for response.

        Args:
            instance: Server instance
            method: LSP method name
            params: Method parameters
            timeout: Timeout in seconds

        Returns:
            Response result or None on error
        """
        from .supervisor_tools import get_supervisor

        request_id = _get_next_request_id()
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        instance.pending_requests[request_id] = future

        try:
            # Send the message
            await self._send_message(instance, message)
            instance.last_activity = time.time()

            # Wait for response
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            debug_log.warning(
                f"LSP request timeout: {method}",
                category=Category.SUPERVISOR,
            )
            return None
        finally:
            instance.pending_requests.pop(request_id, None)

    async def _send_notification(
        self,
        instance: LSPServerInstance,
        method: str,
        params: dict,
    ) -> None:
        """Send a JSON-RPC notification (no response expected).

        Args:
            instance: Server instance
            method: LSP method name
            params: Method parameters
        """
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        await self._send_message(instance, message)

    async def _send_message(
        self,
        instance: LSPServerInstance,
        message: dict,
    ) -> None:
        """Send a JSON-RPC message with Content-Length header.

        Args:
            instance: Server instance
            message: Message to send
        """
        from .supervisor_tools import get_supervisor

        supervisor = get_supervisor()
        if not supervisor:
            raise RuntimeError("Supervisor not initialized")

        # Encode message with Content-Length header
        content = json.dumps(message)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        full_message = header + content

        # Send via supervisor stdin
        supervisor.send_input(instance.process_id, full_message)

        debug_log.debug(
            f"LSP send: {message.get('method', 'response')}",
            category=Category.SUPERVISOR,
            details={"id": message.get("id")},
        )

    async def _handle_server_output(self, instance: LSPServerInstance) -> None:
        """Background task to handle server output.

        Reads from supervisor output. In LSP mode, the Rust supervisor already
        handles Content-Length framing, so each log entry is a complete JSON-RPC
        message.
        """
        from .supervisor_tools import get_supervisor

        supervisor = get_supervisor()
        if not supervisor:
            return

        last_check = 0.0

        while True:
            try:
                # Get new output - each entry is already a complete JSON-RPC message
                # because the Rust supervisor parses Content-Length framing
                output_json = await supervisor.get_output(
                    instance.process_id,
                    limit=100,
                    source="stdout",
                    since=last_check,
                )
                logs = json.loads(output_json)

                for log in logs:
                    content = log.get("content", "")
                    if content:
                        # Each content is already a complete JSON-RPC message
                        try:
                            message = json.loads(content)
                            await self._handle_message(instance, message)
                        except json.JSONDecodeError as e:
                            debug_log.warning(
                                f"LSP parse error: {e}",
                                category=Category.SUPERVISOR,
                                details={"content_preview": content[:200]},
                            )

                last_check = time.time()
                await asyncio.sleep(0.1)  # Poll interval

            except asyncio.CancelledError:
                break
            except Exception as e:
                debug_log.error(
                    f"LSP output handler error: {e}",
                    category=Category.SUPERVISOR,
                )
                await asyncio.sleep(1.0)

    async def _handle_message(
        self,
        instance: LSPServerInstance,
        message: dict,
    ) -> None:
        """Handle a parsed JSON-RPC message.

        Routes responses to pending requests and handles notifications.
        """
        instance.last_activity = time.time()

        # Check if this is a response
        if "id" in message:
            request_id = message["id"]
            if request_id in instance.pending_requests:
                future = instance.pending_requests[request_id]
                if "error" in message:
                    debug_log.warning(
                        f"LSP error response: {message['error']}",
                        category=Category.SUPERVISOR,
                    )
                    future.set_result(None)
                else:
                    future.set_result(message.get("result"))
                return

        # Check if this is a notification
        if "method" in message:
            method = message["method"]
            params = message.get("params", {})

            # Handle server-initiated notifications
            if method == "textDocument/publishDiagnostics":
                # Could store diagnostics for later retrieval
                pass
            elif method == "window/logMessage":
                level = params.get("type", 3)  # 1=error, 2=warn, 3=info, 4=log
                text = params.get("message", "")
                debug_log.debug(
                    f"LSP log: {text}",
                    category=Category.SUPERVISOR,
                )

    # =========================================================================
    # Public API methods for LLM tools
    # =========================================================================

    async def get_hover(
        self,
        file_path: str,
        line: int,
        character: int,
    ) -> Optional[dict]:
        """Get hover information for a position.

        Args:
            file_path: Absolute path to the file
            line: 0-indexed line number
            character: 0-indexed character position

        Returns:
            Hover result with 'contents' field, or None
        """
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        server_config = config.get_lsp_server_for_file(file_path)
        if not server_config:
            return None

        # Find workspace root
        workspace_root = self._find_workspace_root(file_path, server_config.root_patterns)

        instance = await self.ensure_server(server_config.name, workspace_root)
        if not instance or not instance.initialized:
            return None

        # Open the document first (if not already open)
        await self._ensure_document_open(instance, file_path)

        return await self._send_request(
            instance,
            "textDocument/hover",
            {
                "textDocument": {"uri": f"file://{file_path}"},
                "position": {"line": line, "character": character},
            },
        )

    async def get_definition(
        self,
        file_path: str,
        line: int,
        character: int,
    ) -> Optional[list]:
        """Get definition location(s) for a symbol.

        Args:
            file_path: Absolute path to the file
            line: 0-indexed line number
            character: 0-indexed character position

        Returns:
            List of Location objects, or None
        """
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        server_config = config.get_lsp_server_for_file(file_path)
        if not server_config:
            return None

        workspace_root = self._find_workspace_root(file_path, server_config.root_patterns)
        instance = await self.ensure_server(server_config.name, workspace_root)
        if not instance or not instance.initialized:
            return None

        await self._ensure_document_open(instance, file_path)

        result = await self._send_request(
            instance,
            "textDocument/definition",
            {
                "textDocument": {"uri": f"file://{file_path}"},
                "position": {"line": line, "character": character},
            },
        )

        # Normalize result to list
        if result is None:
            return None
        if isinstance(result, dict):
            return [result]
        return result

    async def get_references(
        self,
        file_path: str,
        line: int,
        character: int,
        include_declaration: bool = True,
    ) -> Optional[list]:
        """Find all references to a symbol.

        Args:
            file_path: Absolute path to the file
            line: 0-indexed line number
            character: 0-indexed character position
            include_declaration: Whether to include the declaration

        Returns:
            List of Location objects, or None
        """
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        server_config = config.get_lsp_server_for_file(file_path)
        if not server_config:
            return None

        workspace_root = self._find_workspace_root(file_path, server_config.root_patterns)
        instance = await self.ensure_server(server_config.name, workspace_root)
        if not instance or not instance.initialized:
            return None

        await self._ensure_document_open(instance, file_path)

        return await self._send_request(
            instance,
            "textDocument/references",
            {
                "textDocument": {"uri": f"file://{file_path}"},
                "position": {"line": line, "character": character},
                "context": {"includeDeclaration": include_declaration},
            },
        )

    async def get_document_symbols(
        self,
        file_path: str,
    ) -> Optional[list]:
        """Get all symbols in a document.

        Args:
            file_path: Absolute path to the file

        Returns:
            List of DocumentSymbol or SymbolInformation objects
        """
        from supervisor_config import get_supervisor_config

        # Check cache first
        cache_key = f"symbols:{file_path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        config = get_supervisor_config()
        server_config = config.get_lsp_server_for_file(file_path)
        if not server_config:
            return None

        workspace_root = self._find_workspace_root(file_path, server_config.root_patterns)
        instance = await self.ensure_server(server_config.name, workspace_root)
        if not instance or not instance.initialized:
            return None

        await self._ensure_document_open(instance, file_path)

        result = await self._send_request(
            instance,
            "textDocument/documentSymbol",
            {
                "textDocument": {"uri": f"file://{file_path}"},
            },
        )

        if result is not None:
            self._cache.set(cache_key, result)

        return result

    async def get_workspace_symbols(
        self,
        workspace_root: str,
        query: str,
        language: str = "python",
    ) -> Optional[list]:
        """Search for symbols across the workspace.

        Args:
            workspace_root: Root directory of the workspace
            query: Symbol search query
            language: Language server to use

        Returns:
            List of SymbolInformation objects
        """
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        server_config = config.get_lsp_server(language)
        if not server_config:
            return None

        instance = await self.ensure_server(server_config.name, workspace_root)
        if not instance or not instance.initialized:
            return None

        return await self._send_request(
            instance,
            "workspace/symbol",
            {"query": query},
        )

    async def get_completion(
        self,
        file_path: str,
        line: int,
        character: int,
    ) -> Optional[dict]:
        """Get completion suggestions.

        Args:
            file_path: Absolute path to the file
            line: 0-indexed line number
            character: 0-indexed character position

        Returns:
            CompletionList or list of CompletionItem
        """
        from supervisor_config import get_supervisor_config

        config = get_supervisor_config()
        server_config = config.get_lsp_server_for_file(file_path)
        if not server_config:
            return None

        workspace_root = self._find_workspace_root(file_path, server_config.root_patterns)
        instance = await self.ensure_server(server_config.name, workspace_root)
        if not instance or not instance.initialized:
            return None

        await self._ensure_document_open(instance, file_path)

        return await self._send_request(
            instance,
            "textDocument/completion",
            {
                "textDocument": {"uri": f"file://{file_path}"},
                "position": {"line": line, "character": character},
            },
        )

    async def _ensure_document_open(
        self,
        instance: LSPServerInstance,
        file_path: str,
    ) -> None:
        """Ensure a document is open in the language server.

        Sends textDocument/didOpen if needed.
        """
        # TODO: Track which documents are open to avoid re-sending
        # For now, always send didOpen (servers handle duplicates)
        try:
            content = Path(file_path).read_text()
        except Exception:
            return

        # Determine language ID from extension
        ext = Path(file_path).suffix.lower()
        language_id = {
            ".py": "python",
            ".pyi": "python",
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".rs": "rust",
            ".go": "go",
        }.get(ext, "plaintext")

        await self._send_notification(
            instance,
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": f"file://{file_path}",
                    "languageId": language_id,
                    "version": 1,
                    "text": content,
                }
            },
        )

    def _find_workspace_root(
        self,
        file_path: str,
        root_patterns: list[str],
    ) -> str:
        """Find the workspace root for a file.

        Walks up from the file looking for root indicator files.
        """
        path = Path(file_path).resolve()
        if path.is_file():
            path = path.parent

        while path != path.parent:
            for pattern in root_patterns:
                if (path / pattern).exists():
                    return str(path)
            path = path.parent

        # Fall back to file's directory
        return str(Path(file_path).parent.resolve())

    async def stop_server(self, server_name: str, workspace_root: str) -> bool:
        """Stop a running LSP server.

        Args:
            server_name: Name of the server
            workspace_root: Workspace root

        Returns:
            True if stopped successfully
        """
        from .supervisor_tools import get_supervisor

        key = self._instance_key(server_name, workspace_root)

        async with self._lock:
            instance = self._instances.pop(key, None)
            if not instance:
                return False

            # Cancel output handler
            handler = self._output_handlers.pop(key, None)
            if handler:
                handler.cancel()

            # Send shutdown request
            try:
                await self._send_request(instance, "shutdown", {}, timeout=5.0)
                await self._send_notification(instance, "exit", {})
            except Exception:
                pass

            # Stop via supervisor
            supervisor = get_supervisor()
            if supervisor:
                try:
                    supervisor.stop_process(instance.process_id)
                except Exception:
                    pass

            debug_log.info(
                f"Stopped LSP server: {server_name}",
                category=Category.SUPERVISOR,
            )
            return True

    async def stop_all_servers(self) -> int:
        """Stop all running LSP servers.

        Returns:
            Number of servers stopped
        """
        keys = list(self._instances.keys())
        count = 0
        for key in keys:
            parts = key.split(":", 1)
            if len(parts) == 2:
                if await self.stop_server(parts[0], parts[1]):
                    count += 1
        return count


# Global LSP client instance
_lsp_client: Optional[LSPClient] = None


def get_lsp_client() -> LSPClient:
    """Get the global LSP client instance."""
    global _lsp_client
    if _lsp_client is None:
        _lsp_client = LSPClient()
    return _lsp_client
