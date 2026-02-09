# Balloons

A TUI (Terminal User Interface) chat client for Claude with session management, context control, and parallel conversation workflows.

Built with [Textual](https://github.com/Textualize/textual).

## Features

- **Session Management** - Persistent conversations stored as JSON, with full history and token tracking
- **Context Control** - Per-turn COPY/COMPRESS/DROP modes to curate what context goes into prompts
- **Fork & Merge** - Git-like branching for parallel exploration without losing context
- **Multi-Backend** - Support for Claude API and OpenAI-compatible endpoints (OpenRouter, llama.cpp)
- **Background Streaming** - Multiple sessions can stream simultaneously
- **Process Supervisor** - Manage long-running background processes (dev servers, builds) with streaming output capture

## Quick Start

### Prerequisites

- Python 3.11+
- [Claude CLI](https://github.com/anthropics/anthropic-tools/tree/main/claude-cli) installed and configured (for Claude backend)

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/balloons.git
cd balloons

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running

```bash
python main.py              # Start new session
python main.py -r <id>      # Resume session by ID
python main.py -l           # List sessions
python main.py -b llama     # Use specific backend
```

## Basic Usage

### Chat Interface

Type your message and press Enter to send. The assistant's response streams in real-time.

### Commands

Commands start with `:` and provide control over sessions and context:

| Command | Description |
|---------|-------------|
| `:new [prompt]` | Create new session |
| `:fork[=name] <prompt>` | Fork with selected context |
| `:merge [summary]` | Merge fork back to parent |
| `:switch [name]` | Switch between sessions/forks |
| `:title <title>` | Set session title |
| `:sup-start <cmd>` | Start a supervised background process |
| `:sup-list` | List running processes |
| `:sup-logs <id>` | Get process output |
| `:sup-stop <id>` | Stop a process |

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+T` | Toggle context tree sidebar |
| `Ctrl+G` | Toggle debug pane |
| `Escape` | Cancel streaming / focus input |
| `Space` (in tree) | Cycle context mode (COPY/COMPRESS/DROP) |

### Context Modes

Control how each turn is included when forking:

- **COPY** - Include verbatim (default)
- **COMPRESS** - LLM summarizes before fork
- **DROP** - Exclude from context

## Configuration

Create `~/.balloons/config.yaml`:

```yaml
default_backend: claude

backends:
  claude:
    # Uses claude CLI (default)

  openrouter:
    type: openai
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: anthropic/claude-sonnet-4
    context_window: 200000

  local-llama:
    type: openai
    base_url: http://localhost:8080/v1
    model: llama-3-70b
    context_window: 8192
```

See `config/config.sample.yaml` for more options.

## Data Storage

Sessions are stored in `~/.balloons/sessions/` as JSON files.

## Documentation

- [FEATURES.md](FEATURES.md) - Complete feature specification
- [CONTEXT-MANAGEMENT.md](CONTEXT-MANAGEMENT.md) - Context system details
- [prompt-samples/](prompt-samples/) - Example system prompts

## Development

```bash
# Run tests
pytest

# Hot reload during development
python main.py --reload
```

## License

MIT
