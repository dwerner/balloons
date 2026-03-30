# Balloons Tools Guide

## CRITICAL: How to Use Tools

**You MUST actually call tools, not just describe your intention to use them.**

Tools are invoked through OpenAI's function calling API. When you want to use a tool, you generate a function call - the system then executes it and returns results. Writing about a tool in your text response does **nothing**.

❌ WRONG - Do NOT write this in your response:
```
I'll now read the file config.py to check the settings.
```

❌ WRONG - This is also bad:
```
Let me make the move e2e4.
```

❌ WRONG - Do NOT try to format tool calls as text:
```
chess_move(move="e2e4")
```

✅ CORRECT - Generate a function call with the tool name and JSON arguments. Do not write text announcing it.

**Key rules:**
1. When you decide to use a tool, **call it immediately** via function call - don't announce what you're going to do
2. After calling a tool, **wait for the result** before continuing
3. Never describe a tool call without actually making it
4. If you find yourself writing "I'll use...", "Let me call...", or "I'm going to..." - STOP and make the function call instead
5. Narrating actions is NOT the same as performing them

This applies to ALL tools: file operations (Read, Write, Edit, Bash, Glob, Grep), chess tools (chess_move, chess_show, etc.), and every other tool available to you.

---

This guide documents additional tools available in Balloons beyond the standard file and shell tools.

## Watcher Tools

If you are a **watcher session** observing another session, you have access to tools for
cross-session communication.

### send_to_target

Send a message to the target session you're watching. The message is queued and delivered
when the target completes its current exchange.

**Parameters:**
- `message` (required): The message to send to the target session

**Example arguments:**
```json
{"message": "Consider using a cache here to improve performance"}
```

**Use cases:**
- Suggesting an alternative approach when the target seems stuck
- Providing a reminder about user instructions
- Sharing relevant context the target might have missed
- Asking the target for information (like session IDs, file paths, etc.)

The message will appear as a user message in the target session, attributed as coming
from your watcher session.


## Process Supervisor Tools

You have access to tools for managing long-running background processes. Use these when you need to:
- Start a dev server, watcher, or long build that should run while you work on other tasks
- Check on the status or output of running processes
- Stop processes when done
- Run commands on remote hosts via SSH

### Why Use the Supervisor?

The regular `Bash` tool waits for commands to complete, which blocks your workflow for long-running processes. The supervisor tools let you:
- **Start processes in background**: Run `npm run dev` or `cargo watch` without blocking
- **Check output later**: Query process output at any time
- **Session-scoped**: Processes are tied to the session and cleaned up appropriately
- **Remote execution**: Run commands on SSH-accessible hosts defined in supervisor.yaml

### Available Tools

**supervisor_start** - Start a background process
- `command` (required): Shell command to execute
- `host` (optional): Host from supervisor.yaml (default: "local"). Use supervisor_query to find available hosts.
- `name` (optional): Friendly name for the process (e.g., "dev-server", "test-watcher")
- `working_dir` (optional): Working directory. Defaults to session working directory.
- `env` (optional): Additional environment variables as key-value pairs

**supervisor_list** - List processes
- `all_sessions` (optional): If true, list processes from all sessions. Default: only current session.
- `host` (optional): Filter to specific host.

**supervisor_output** - Get process output
- `process_id` (required): The process ID from supervisor_start or supervisor_list
- `limit` (optional): Maximum number of log entries to return. Default: 50

**supervisor_stop** - Stop a process
- `process_id` (required): The process ID to stop

**supervisor_query** - Query available hosts
- `tags` (optional): Filter by tags (must have ALL specified tags)
- `type` (optional): Filter by type ("local" or "ssh")

**supervisor_host_status** - Check host connectivity
- `host` (required): Host name from supervisor.yaml

### Typical Workflow

1. **Start a dev server** - call `supervisor_start` with:
   ```json
   {"command": "npm run dev", "name": "frontend"}
   ```
   Returns a process_id for later reference.

2. **Check if it's running** - call `supervisor_list` with:
   ```json
   {}
   ```
   Shows all processes with their status (running/exited/failed).

3. **View recent output** - call `supervisor_output` with:
   ```json
   {"process_id": "abc123", "limit": 20}
   ```
   Shows the last 20 log entries (stdout/stderr).

4. **Stop when done** - call `supervisor_stop` with:
   ```json
   {"process_id": "abc123"}
   ```

### Remote Host Workflow

1. **Query available hosts** - call `supervisor_query` with:
   ```json
   {"tags": ["docker"]}
   ```
   Returns hosts with docker capability.

2. **Check host is reachable** - call `supervisor_host_status` with:
   ```json
   {"host": "gpu-box"}
   ```
   Returns connectivity status and latency.

3. **Run command on remote host** - call `supervisor_start` with:
   ```json
   {"command": "nvidia-smi", "host": "gpu-box", "name": "gpu-check"}
   ```
   Executes via SSH, streams output back.

### Good Use Cases

- **Dev servers**: `npm run dev`, `python manage.py runserver`, `cargo run`
- **File watchers**: `cargo watch -x test`, `nodemon`, `inotifywait` loops
- **Long builds**: `make all`, `cargo build --release`, `docker build`
- **Database/services**: `docker-compose up`, `redis-server`
- **Remote commands**: GPU monitoring, remote builds, deployment tasks

### Process Status

Processes report one of three states:
- `{"state": "running", "pid": 12345}` - Currently running
- `{"state": "exited", "code": 0, "signal": null}` - Completed normally
- `{"state": "failed", "error": "message"}` - Failed to start or crashed

### Log Entry Format

Each log entry contains:
- `timestamp`: ISO datetime when the entry was captured
- `source`: "stdout", "stderr", or "system"
- `content`: The actual log line text

### Notes

- Processes are scoped to the current session
- Up to 10,000 log entries are kept per process (circular buffer)
- Log entries include timestamp, source (stdout/stderr/system), and content
- When a session closes, its processes can be stopped automatically
- The process and its logs are retained after stopping, so you can still query output
- Remote host SSH keys should be configured in ~/.ssh/config or ssh-agent


## Workflow Tools

### propose_fork

Propose creating a new conversation branch with curated context.

Use when:
- You've finished planning and are ready to start implementation
- The conversation has accumulated irrelevant context (debugging, abandoned approaches)
- Context usage is high (>50%) and you're starting a substantial new task

Parameters:
- `name`: Short fork name (e.g., "implement-cache")
- `description`: What this fork will accomplish
- `context_plan`: Array of context assignments with exchange_range, mode (copy/compress/drop), and reason
- `initial_prompt`: Starting prompt for the fork

### propose_merge

Propose merging fork work back to parent session.

Use when:
- Implementation task is complete (or a milestone is reached)
- Tests are passing
- User has confirmed the work meets requirements

Note: Forks can be merged multiple times. After merging, you can continue working
in the fork and merge again to capture additional progress.

Parameters:
- `summary` (required): 1-3 sentence summary of what was accomplished
- `reason` (optional): Why merge now?
- `files_changed` (optional): List of modified files
- `key_accomplishments` (optional): Bullet points of what was done


## Link Navigation Tools

### list_links
List all explicit links from the current session.

### follow_link
Load context from a linked or related session.
- `link_id` or `session_id`: Which session to load
- `limit`: Number of turns to return (default 10)
- `offset`: Turn index to start from
- `full_content`: If true, returns full content (up to 100k chars)

### search_linked_session
Search within a linked session's history.
- `link_id` (required): The session to search
- `query` (required): Search query
- `limit`, `offset`, `full_content`: Pagination and content options

### session_info
Get information about the current session including context usage and fork tree.


## Slide Creation

### create_slide
Create presentation slides that appear in the Slides tab.
- `title`: Slide title (max ~50 chars)
- `content`: Markdown content (max ~10 lines)
- `notes`: Optional speaker notes


## Goal Management Tools

Track goals, plans, and todos across sessions.

**IMPORTANT**: Always use these goal management tools instead of CLI commands like `:goals`,
`:plans`, or `:todos`. The tools provide richer information and integrate better with your
workflow. Specifically:
- Use `list_goals` instead of `:goals`
- Use `list_plans` instead of `:plans`
- Use `list_todos` instead of `:todos`
- Use `get_hierarchy` to understand how goals, plans, and todos relate to each other

### Available Tools

**create_goal** - Create a new goal with acceptance criteria
- `title`, `description`, `weight` (1-10), `acceptance_criteria` (array)

**update_goal** - Update an existing goal (rename, change weight, etc.)
- `goal_id` (required), `title`, `description`, `weight`, `acceptance_criteria`, `status`

**create_plan** - Create a plan for a goal
- `goal_id`, `title`, `description`, `status` ("draft" or "active")

**create_todo** - Create a todo for a plan
- `plan_id`, `title`, `description`, `is_spike`, `timebox_minutes`, `depends_on`
- **Check `list_todos` first for duplicates** before creating

**update_todo** - Update an existing todo (rename, change status, etc.)
- `todo_id` (required), `title`, `description`, `status`, `is_spike`, `timebox_minutes`, `plan_id` (reparent)

**delete_todo** - Permanently delete a todo
- `todo_id` (required): ID of the todo to delete (can be prefix)
- Removes todo, plan links, dependencies, and session bindings
- Consider `update_todo` with `status: "abandoned"` to preserve history instead

**list_goals** - List goals (optionally include completed)

**list_plans** - List plans (filter by goal_id). Use to find plan IDs for create_todo.

**list_todos** - List priority-ranked todos (optionally filter by plan)

**get_hierarchy** - Get complete hierarchy for any entity (goal, plan, or todo)
- `entity_type` (required): "goal", "plan", or "todo"
- `entity_id` (required): ID of the entity (can be prefix)
- `include_bindings`: Show session bindings (default: true)
- `include_dependencies`: Show todo dependencies (default: true)

Use `get_hierarchy` to understand context and relationships:
- For a **todo**: Shows parent plans, goal, and all dependencies
- For a **plan**: Shows parent goal and all todos under it
- For a **goal**: Shows all plans and their todos

Returns: goal info, related plans, related todos with status, dependencies (with cycle detection), and session bindings.

**mark_todo_done** - Mark a todo complete (triggers lifecycle hooks)

**bind_session** - Bind session to goal/plan/todo with role

**begin_streaming_todo** - Start background sessions for todos
- `todo_ids` (required): List of todo IDs to start sessions for (can be prefixes)
- `initial_prompts` (optional): Map of todo_id -> custom initial prompt

Creates new sessions bound to the specified todos and begins streaming in the background.
The user will see a confirmation modal with checkboxes to select which todos to start.
Each started session is bound to the todo with `role: implementation` and the todo status
is updated to `in_progress`.

### Session Binding Management

Tools for reviewing and managing session bindings in bulk:

**list_all_bindings** - View all session bindings (paginated)
- `filter`: "all", "active", "orphaned", "released" (default: "active")
- `goal_id`: Only show bindings under this goal
- `mode`: "summary" for counts, "detail" for full list
- `limit`: Max entities per page (default: 10)
- `offset`: Skip N entities for pagination (default: 0)

**rebind_session** - Rebind any session (not just current)
- `session_id` (required): Session to rebind
- `entity_type` (required): "goal", "plan", or "todo"
- `entity_id` (required): Entity to bind to
- `role`: Session role (default: "implementation")

**bind_entity_to_sessions** - Bulk bind entity to multiple sessions
- `entity_type` (required): "goal", "plan", or "todo"
- `entity_id` (required): Entity to bind
- `session_ids` (required): List of session IDs
- `role`: Role for all sessions
- `unbind_others`: If true, unbind sessions not in list

**unbind_sessions** - Bulk unbind
- `session_ids`: Specific sessions to unbind
- `orphans_only`: If true, only cleanup orphaned bindings

#### Binding Cleanup Workflow

1. Call `list_all_bindings` with `{"mode": "summary"}` - Get overview
2. Call `list_all_bindings` with `{"filter": "orphaned"}` - Find problems
3. Call `unbind_sessions` with `{"orphans_only": true}` - Clean orphans
4. Call `rebind_session` with the appropriate session and entity IDs - Fix specific bindings

### Goal-Driven Session Workflow

Goals integrate with the fork/merge workflow. Each phase uses a dedicated session:

#### 1. Interview Session (via `:goal-interview` command)
- User triggers goal creation with `:goal-interview=title <prompt>` command (both required)
- The command creates a new session and provides interview guidance
- Discuss scope, constraints, and acceptance criteria with the user
- **CREATE the goal in this session** so it persists before forking
- **Bind this session** to the goal with `role: interview`
- When interview is complete, **propose a fork** for planning

#### 2. Planning Session (fork from interview)
- **Bind to the existing goal** with `role: planning` (do NOT create it again)
- Create the plan with phases/milestones
- Break down into concrete todos with dependencies
- When planning is complete, **propose a merge** back to interview session
- Then **propose a fork** for the first implementation todo

#### 3. Implementation Sessions (forks from planning)
- One fork per todo (keeps context focused)
- **Bind to the specific todo** with `role: implementation`
- Do the implementation work
- **Mark todo done** when complete
- **Propose a merge** back to planning session

#### 4. Postmortem Session (when all todos complete)
- Triggered when last todo is marked done
- Review what was accomplished vs. acceptance criteria
- Decide: goal complete, needs revision, or spawn follow-up goals

**Key principles:**
- **Create goals in root sessions** - they persist across forks
- **Bind sessions before working** - keeps context focused
- **One todo per implementation fork** - clean context, clear merges
- **Merge back after each phase** - progress is recorded in parent


## User Input Tool

### ask_user

**Stop and ask the user a question, waiting for their response.**

Use this tool when you need clarification, confirmation, or input before proceeding. When you call this tool, the agentic loop will **stop** and wait for the user to respond.

**Parameters:**
- `question` (required): The question to ask. Be clear and specific.
- `context` (optional): Additional context to help the user answer (tradeoffs, implications)
- `options` (optional): Array of suggested options for the user to choose from

**Example - Simple clarification:**
```json
{"question": "Which database would you prefer - PostgreSQL or SQLite?"}
```

**Example - With context and options:**
```json
{
  "question": "How should I handle authentication?",
  "context": "JWT is stateless but requires token refresh logic. Session cookies are simpler but need server-side storage.",
  "options": ["JWT tokens", "Session cookies", "OAuth only"]
}
```

**When to use:**
- You need clarification about requirements or preferences
- You want confirmation before taking a significant action (e.g., deleting files)
- You're unsure which approach the user prefers
- You need additional information to proceed

**When NOT to use:**
- For rhetorical questions in your response text - just write them normally
- For status updates - just include them in your response
- For questions you can answer yourself from context

**IMPORTANT:** This tool **stops** the agentic loop. Do not continue generating tool calls after `ask_user` - wait for the user's response.


## MIDI Player

**REMINDER: Call tools, don't describe them.** When you want to play notes, invoke `play_midi` directly.

### play_midi
Play musical notes through the browser using Web Audio synthesis.
- `notes` (required): Space-separated note sequence (e.g., "C4 D4 E4:h [C4,E4,G4]:w")
- `bpm` (required): Tempo 60-240
- `waveform` (optional): "sine", "square", "sawtooth", "triangle"
- `volume` (optional): 0-1

Notation: Notes like `C4`, `D#5`, `Eb3`. Durations: `:w` whole, `:h` half, `:q` quarter (default), `:e` eighth, `:s` sixteenth. Rests: `R`. Chords: `[C4,E4,G4]`.


<!-- #include shared/debug-logging.md -->
