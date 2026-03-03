# LSP Integration

Balloons supports Language Server Protocol (LSP) integration, allowing the LLM to query language servers for semantic code understanding. This provides type information, go-to-definition, find references, and other IDE-like features.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LSP Integration Stack                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LLM Tools                              TypeScript UI                        │
│  ┌─────────────────────┐               ┌─────────────────────────────────┐  │
│  │ lsp_hover           │               │ LSPServiceClient                │  │
│  │ lsp_definition      │               │ - getStatus()                   │  │
│  │ lsp_references      │               │ - startServer()                 │  │
│  │ lsp_symbols         │               │ - stopServer()                  │  │
│  │ lsp_status          │               │ - restartServer()               │  │
│  │ lsp_start/stop      │               └────────────────┬────────────────┘  │
│  └──────────┬──────────┘                                │                   │
│             │                                           │ WebSocket         │
│             ▼                                           ▼                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    LSPClient (core/lsp_client.py)                    │   │
│  │  - Manages server instances per workspace                            │   │
│  │  - JSON-RPC request/response correlation                             │   │
│  │  - Response caching                                                  │   │
│  └────────────────────────────────┬────────────────────────────────────┘   │
│                                   │ supervisor.start(mode="lsp")            │
│                                   ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │              Rust Supervisor (ProcessMode::Lsp)                      │   │
│  │  - Content-Length framing via lsp-framing crate                      │   │
│  │  - Each log entry = complete JSON-RPC message                        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

### Required: Install Language Servers

LSP integration requires language servers to be installed on the system. The servers must be accessible via `$PATH`.

#### Python (Pyright)

```bash
npm install -g pyright
```

This installs `pyright-langserver` which provides Python type checking and intellisense.

#### TypeScript/JavaScript

```bash
npm install -g typescript typescript-language-server
```

This installs `typescript-language-server` which wraps the TypeScript compiler for LSP.

#### Rust

```bash
rustup component add rust-analyzer
```

This installs `rust-analyzer` via rustup. Note: This requires rustup, not a system-installed Rust.

#### Go

```bash
go install golang.org/x/tools/gopls@latest
```

This installs `gopls`, the official Go language server.

### Verifying Installation

Check that language servers are accessible:

```bash
# Python
pyright-langserver --version

# TypeScript
typescript-language-server --version

# Rust
rust-analyzer --version

# Go
gopls version
```

## Configuration

LSP server definitions are stored in `~/.balloons/supervisor.yaml`:

```yaml
lsp_servers:
  python:
    command: pyright-langserver --stdio
    extensions: [.py, .pyi]
    languages: [python]
    idle_timeout_seconds: 300

  typescript:
    command: typescript-language-server --stdio
    extensions: [.ts, .tsx, .js, .jsx]
    languages: [typescript, javascript]
    idle_timeout_seconds: 300

  rust:
    command: rust-analyzer
    extensions: [.rs]
    languages: [rust]
    idle_timeout_seconds: 600

  go:
    command: gopls
    extensions: [.go]
    languages: [go]
    idle_timeout_seconds: 300
```

Default configurations are provided if the file doesn't exist.

## LLM Tools

The following tools are available to the LLM:

### `lsp_hover`

Get type information and documentation for a symbol at a position.

```python
lsp_hover(file_path="src/auth.py", line=42, character=10)
# Returns: Type signature, docstring, etc.
```

### `lsp_definition`

Find where a symbol is defined.

```python
lsp_definition(file_path="src/main.py", line=10, character=5)
# Returns: File path and position of definition
```

### `lsp_references`

Find all usages of a symbol.

```python
lsp_references(file_path="src/utils.py", line=42, character=4)
# Returns: All files and positions where symbol is used
```

### `lsp_symbols`

Get all symbols in a file.

```python
lsp_symbols(file_path="src/models.py")
# Returns: Hierarchical list of classes, functions, variables
```

### `lsp_workspace_symbols`

Search for symbols across the workspace.

```python
lsp_workspace_symbols(query="Cache")
# Returns: All matching symbols across all files
```

### `lsp_status`

Get status of configured and running LSP servers.

```python
lsp_status()
# Returns: Configured servers, running instances, idle time, etc.
```

### `lsp_start`

Manually start an LSP server.

```python
lsp_start(language="python")
lsp_start(language="rust", workspace="/path/to/project")
```

### `lsp_stop`

Stop a running LSP server.

```python
lsp_stop(language="python")
lsp_stop(key="python:/path/to/workspace")
```

### `lsp_restart`

Restart an LSP server (clears cached state).

```python
lsp_restart(language="typescript")
```

## WebSocket API

The `LSPService` exposes LSP management via WebSocket:

### Methods

- `getStatus()` - Get all configured and running servers
- `startServer(language, workspace?)` - Start a server
- `stopServer(language?, workspace?, key?)` - Stop a server
- `restartServer(language?, workspace?, key?)` - Restart a server
- `stopAllServers()` - Stop all running servers

### Events

- `lspServerStarted` - Emitted when a server starts
- `lspServerStopped` - Emitted when a server stops
- `lspServerRestarted` - Emitted when a server restarts

## How It Works

### Content-Length Framing

LSP uses HTTP-style headers to frame JSON-RPC messages:

```
Content-Length: 234\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"initialize",...}
```

The `lsp-framing` Rust crate (in `balloons-rs/crates/lsp-framing/`) provides a nom-based parser for this format.

### Process Management

LSP servers are managed by the supervisor system:

1. When an LSP query is made, the client checks if a server is running
2. If not, it starts one via `supervisor.start(mode="lsp")`
3. The Rust supervisor uses `ProcessMode::Lsp` to enable Content-Length framing
4. Each JSON-RPC response is delivered as a complete log entry
5. The Python client correlates responses to pending requests

### Instance Keys

Each LSP server instance is identified by `{language}:{workspace_root}`:

- `python:/home/user/project`
- `rust:/home/user/rust-project`

This allows multiple instances of the same language server for different workspaces.

## Troubleshooting

### Server not starting

1. Verify the language server is installed: `which pyright-langserver`
2. Check the command in `~/.balloons/supervisor.yaml`
3. Use `lsp_status()` to see configured servers

### Server crashes immediately

1. Check supervisor output: Use the Supervisor tab in the UI
2. Look for stderr messages in the process logs
3. Try running the command manually: `pyright-langserver --stdio`

### No responses

1. Check if server is initialized: `lsp_status()` shows `initialized: true`
2. Verify the workspace path is correct
3. Check for JSON-RPC errors in the response

### Performance

- Servers are kept running to avoid startup cost
- Default idle timeout is 5 minutes (300 seconds)
- Rust-analyzer uses 10 minutes due to slower startup
- Response caching reduces redundant queries
