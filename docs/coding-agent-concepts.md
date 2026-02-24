# Coding Agent: Architecture and Learnings

*A conceptual document preserving the vision and key learnings from the coding-agent project (December 2025 - January 2026), a Kotlin-based exploration of modular agent architecture with plugin systems, tool confirmation, and context management.*

## Vision

A **modular coding assistant** built around:
1. **Plugin architecture** - Everything is a plugin: tools, commands, transports, routes
2. **Tool confirmation flow** - Human-in-the-loop with y/n/a/b/e (yes/no/allow-all/abort/explain)
3. **Multiple transports** - CLI, HTTP, WebSocket - all sharing the same agent loop
4. **Snapshots for context** - Save/restore conversation state as structured YAML
5. **Local LLM support** - OpenAI-compatible API targeting llama.cpp

---

## Core Architecture

### The Brain

The `KoogBrain` is the central orchestrator:

```
KoogBrain
├── LLMClient (OpenAI-compatible HTTP client)
├── PluginManager (dependency-ordered lifecycle)
├── AgentLoop (unified tool execution loop)
├── Contexts (conversation state per session)
└── Transports (CLI, HTTP, WebSocket)
```

### Plugin System

Everything is a plugin with a common interface:

```kotlin
interface Plugin {
    val id: String                    // Unique identifier
    val name: String                  // Human-readable name
    val description: String           // What it does
    val dependencies: List<String>    // Other plugin IDs we need

    fun initialize()
    fun shutdown()
}
```

**Plugin types:**

| Type | Purpose | Example |
|------|---------|---------|
| `ToolPlugin` | LLM-callable tools | `listDirectory`, `editFile`, `shellCommand` |
| `CommandPlugin` | CLI slash commands | `/help`, `/model` |
| `TransportPlugin` | Input/output channels | CLI, HTTP, WebSocket |
| `HttpRoutePlugin` | REST endpoints | Git state API |
| `StoragePlugin` | Persistence | (placeholder) |

### Plugin Manager

Handles lifecycle with dependency resolution:

```kotlin
class PluginManager {
    fun register(plugin: Plugin)
    fun initializeAll()  // Topological sort by dependencies
    fun shutdownAll()    // Reverse order
    fun reload(id: String, newPlugin: Plugin)  // Hot reload with notification
    fun getByType<T>(type: Class<T>): List<T>
}
```

**Key features:**
- Topological sort ensures dependencies initialize first
- Dependency injection via `NeedsDependencies`, `NeedsConfig`, `NeedsBrain`
- Hot reload with `DependencyAware` notification
- Circular dependency detection

---

## Tool Confirmation Flow

A key innovation: **human-in-the-loop tool execution** with multiple confirmation modes.

### The Confirmation Options

| Key | Action | Scope |
|-----|--------|-------|
| `y` | Execute this tool | Single tool |
| `n` | Skip this tool | Single tool |
| `a` | Allow all remaining | Rest of task |
| `b` | Abort entire task | Task |
| `e` | Explain first | Request explanation |

### The Flow

```
LLM Response
    │
    ├─ Text only? → Return to user
    │
    └─ Tool calls? → For each tool:
           │
           ├─ Allow-all mode? → Execute directly
           │
           └─ Needs confirmation?
                  │
                  ├─ CLI: Prompt interactively
                  │     └─ (e) Explain → Get explanation → Re-prompt
                  │
                  └─ HTTP: Return pending state
                        └─ Client sends confirm response
                        └─ Continue from where we left off
```

### Implementation Insight

The "Explain" option calls the LLM with a targeted prompt:

```kotlin
val explainPrompt = """
Before executing the ${toolName} tool with arguments: ${sanitizedArgs}
Please explain in 1-2 sentences what you're doing and why.
"""
```

This gives users insight into agent reasoning without exposing internal prompts.

---

## Agent Loop

A unified loop that works with any transport:

```kotlin
class AgentLoop(
    llmClient: LLMClientInterface,
    tools: List<ToolPlugin>,
    io: AgentSessionIO,
    maxSteps: Int = 1000
) {
    suspend fun run(context: AgentContext): TaskResult {
        while (stepCount < maxSteps) {
            // 1. Process any injected context
            processInjections(context)

            // 2. Call LLM with streaming
            val response = llmClient.chatStreaming(history, tools) { token ->
                io.onToken(token)
            }

            // 3. No tools? Done.
            if (response.toolCalls.isNullOrEmpty()) {
                return TaskResult(success = true, response = response.content)
            }

            // 4. Execute each tool with confirmation
            for (toolCall in response.toolCalls) {
                val result = executeToolCall(context, toolCall)
                // Handle abort, skip, etc.
            }
        }
    }
}
```

**Key features:**
- Checks for context injections before each LLM call (mid-turn interjections)
- Streaming support with token callback
- Uniform handling of CLI vs HTTP confirmation
- Recoverable vs non-recoverable error detection

---

## Context Snapshots

Save and restore conversation state as structured YAML:

```yaml
version: 1
timestamp: "2026-01-08T10:30:00Z"
conversation_id: "abc123"
project_path: "/home/dan/myproject"

summary: "Implemented caching layer with Redis backend"
key_decisions:
  - "Used Redis instead of memcached for persistence"
  - "Cache TTL set to 5 minutes based on usage patterns"
files_modified:
  - "src/cache.py (created)"
  - "src/config.py (modified)"
current_state: "Tests passing, ready for review"
next_steps:
  - "Add cache invalidation on writes"
  - "Add metrics collection"

recent_messages:
  - role: USER
    content: "Add caching to the API"
  - role: ASSISTANT
    content: "I'll implement a Redis-based cache..."
```

### Restoration Prompt

When loading a snapshot, it's converted to a restoration prompt:

```
## Restored Context from Previous Session

This conversation is being restored from a snapshot taken at 2026-01-08T10:30:00Z.

### Summary of Previous Work
Implemented caching layer with Redis backend

### Key Decisions Made
- Used Redis instead of memcached for persistence
- Cache TTL set to 5 minutes based on usage patterns

### Files Modified
- src/cache.py (created)
- src/config.py (modified)

### Current State
Tests passing, ready for review

### Suggested Next Steps
- Add cache invalidation on writes
- Add metrics collection

---
Continue from where you left off. The user may provide additional instructions.
```

---

## System Prompt: Pragmatic Principles

The system prompt embeds principles from The Pragmatic Programmer:

### Core Principles

| Principle | Application |
|-----------|-------------|
| **DRY** | Search codebase before writing new code |
| **Orthogonality** | Make self-contained changes |
| **Tracer Bullets** | Implement thin end-to-end slices first |
| **Broken Windows** | Fix things properly, no hacks |
| **Good Enough** | Deliver working solutions, don't over-engineer |
| **Reversibility** | Prefer changes easy to undo |
| **Design by Contract** | Make expectations explicit |
| **Assertive Programming** | Crash early on impossible conditions |
| **Don't Program by Coincidence** | Understand why things work |
| **Refactor Early** | Clean up code as you go |

### Workflow Guidelines

```
1. Understand Before Acting
   - Explore codebase structure first
   - Read relevant files before changes
   - Search for existing patterns (DRY)

2. Make Targeted Changes
   - Use editFile with precise oldText
   - Keep changes orthogonal

3. Verify Your Changes
   - Run build commands
   - Run test commands
   - Fix errors before considering done

4. Context Management
   - For large files, use startLine/endLine
   - Focus on relevant sections
```

---

## LLM Client

OpenAI-compatible HTTP client with llama.cpp extensions:

```kotlin
interface LLMClientInterface {
    suspend fun chat(history: List<Message>, tools: List<ToolPlugin>): Message
    suspend fun chatStreaming(
        history: List<Message>,
        tools: List<ToolPlugin>,
        tokenCallback: TokenCallback
    ): Message

    val contextInfo: ContextInfo?  // Token usage tracking
    suspend fun fetchContextInfo(): ContextInfo?  // Query /slots endpoint
}
```

### Context Tracking

```kotlin
data class ContextInfo(
    val contextSize: Int,      // Total context window (n_ctx)
    val promptTokens: Int,     // Tokens used by prompt
    val completionTokens: Int, // Tokens generated
    val totalUsed: Int,        // Total tokens used
    val remaining: Int         // Remaining available
)
```

**Key insight:** The llama.cpp `/slots` endpoint provides accurate context usage, enabling proactive context management.

### XML Tool Call Parsing

Fallback for models that output tools as XML instead of JSON:

```xml
<function=listDirectory>
  <parameter=path>/home/dan/project</parameter>
  <parameter=maxDepth>2</parameter>
</function>
```

This allows compatibility with models that don't support native function calling.

---

## Transport Architecture

### CLI Transport

- Interactive readline loop
- Token streaming to stdout
- Tool confirmation via stdin prompts
- Graceful shutdown on Ctrl+C

### HTTP Transport

- REST endpoint: `POST /task`
- Status endpoint: `GET /status`
- Plugins endpoint: `GET /plugins`
- Returns JSON with:
  - Success/error status
  - Response text
  - Pending tool info (if awaiting confirmation)
  - Captured logs

### WebSocket Transport

- Real-time streaming tokens
- Context injection mid-turn
- Bidirectional communication

---

## Hot Reload

The system supports hot-reloading external plugins:

```
1. File watcher detects JAR change
2. If tasks running: stage reload for later
3. When tasks complete:
   a. Capture state (contexts)
   b. Notify dependents of unloading
   c. Close old classloaders
   d. Load new plugins from JARs
   e. Re-initialize with dependency injection
   f. Restore state
```

**Key insight:** ClassLoader isolation enables replacing plugin code without restarting the JVM.

---

## Plugin Contract Validation

Before loading, plugins are validated:

```kotlin
object PluginContract {
    fun validateTool(plugin: ToolPlugin): ValidationResult {
        // Check: id, name, description not blank
        // Check: getTools() doesn't throw
        // Check: at least one tool provided
        // Check: tool names are valid identifiers
        // Check: parameters have names and descriptions
    }
}
```

This catches plugin bugs early, before they cause runtime failures.

---

## Learnings and Insights

### What Worked Well

**1. Plugin architecture**
- Clean separation of concerns
- Easy to add new tools, commands, endpoints
- Hot reload enables rapid iteration

**2. Tool confirmation flow**
- "Explain" option builds trust
- "Allow-all" reduces friction for known-good sequences
- Abort provides escape hatch

**3. Multiple transports sharing one loop**
- DRY - logic isn't duplicated per transport
- Consistent behavior across interfaces

**4. Snapshots for context**
- Structured format captures essentials
- Restoration prompt integrates naturally
- Human-readable YAML for inspection

### Challenges Encountered

**1. HTTP confirmation state**
- Need to persist pending tool state between requests
- Conversation ID required to continue

**2. ClassLoader complexity**
- Hot reload requires careful ClassLoader management
- Classes loaded by old loader can't see new classes

**3. LLM compatibility**
- Different models have different tool call formats
- XML fallback required for some models
- Streaming accumulation is tricky

**4. Context window management**
- llama.cpp `/slots` endpoint gives token counts
- But proactive management (when to summarize/truncate) is still manual

---

## Relationship to Balloons

Several concepts from coding-agent informed Balloons:

| Coding Agent Concept | Balloons Evolution |
|---------------------|-------------------|
| Tool confirmation (y/n/a/b/e) | Evolved into confirmation UI |
| Snapshots | Became session persistence + archive blocks |
| Context tracking | Token counting + context curation |
| Multiple transports | WebSocket service architecture |
| Plugin system | Less modular but simpler Python approach |
| System prompt principles | Influences CLAUDE.md patterns |

---

## Concepts Worth Preserving

### 1. Tool Confirmation Flow

The y/n/a/b/e pattern is valuable:
- Granular control without friction
- "Explain" builds understanding
- Scoped "allow-all" balances safety and speed

### 2. Structured Snapshots

The snapshot format captures:
- What was done (summary)
- Why (key decisions)
- What changed (files modified)
- What's next (suggested steps)

This is more useful than raw conversation history.

### 3. Plugin Validation

Contract validation catches bugs early:
- Required fields present
- Types correct
- Descriptions meaningful

### 4. Context Info from LLM

Querying the LLM server for context usage enables:
- Proactive warnings before hitting limits
- Informed decisions about when to compress

### 5. Pragmatic Principles in Prompts

Embedding methodology in the system prompt:
- Makes behavior predictable
- Encourages good practices
- Teaches through example

---

## Future Integration Possibilities

### Tool Confirmation in Balloons

The y/n/a/b/e flow could enhance Balloons:
- Currently tools run without confirmation
- Could add confirmation for destructive operations
- "Explain" would work well with the existing UI

### Structured Session Summaries

Adopt the snapshot format for merge summaries:
- Summary of work done
- Key decisions made
- Files changed
- Next steps

This is already partially implemented in `MergeBlock`.

### Context Tracking from LLM

For OpenRouter/local models:
- Track context usage per turn
- Display in UI (already have some of this)
- Warn when approaching limits

### Plugin System (Maybe)

A plugin system could enable:
- Custom tools per project
- User-defined commands
- But adds complexity - evaluate need first

---

*This document preserves concepts from the coding-agent project for future reference and potential integration into Balloons or similar systems.*
