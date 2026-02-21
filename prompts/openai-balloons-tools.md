# Balloons Tools Guide

This guide documents additional tools available in Balloons beyond the standard file and shell tools.

## Process Supervisor Tools

You have access to tools for managing long-running background processes. Use these when you need to:
- Start a dev server, watcher, or long build that should run while you work on other tasks
- Check on the status or output of running processes
- Stop processes when done

### Why Use the Supervisor?

The regular `Bash` tool waits for commands to complete, which blocks your workflow for long-running processes. The supervisor tools let you:
- **Start processes in background**: Run `npm run dev` or `cargo watch` without blocking
- **Check output later**: Query process output at any time
- **Session-scoped**: Processes are tied to the session and cleaned up appropriately

### Available Tools

**supervisor_start** - Start a background process
- `command` (required): Shell command to execute
- `name` (optional): Friendly name for the process (e.g., "dev-server", "test-watcher")
- `working_dir` (optional): Working directory. Defaults to session working directory.
- `env` (optional): Additional environment variables as key-value pairs

**supervisor_list** - List processes
- `all_sessions` (optional): If true, list processes from all sessions. Default: only current session.

**supervisor_output** - Get process output
- `process_id` (required): The process ID from supervisor_start or supervisor_list
- `limit` (optional): Maximum number of log entries to return. Default: 50

**supervisor_stop** - Stop a process
- `process_id` (required): The process ID to stop

### Typical Workflow

1. **Start a dev server**:
   ```
   supervisor_start(command="npm run dev", name="frontend")
   ```
   Returns a process_id for later reference.

2. **Check if it's running**:
   ```
   supervisor_list()
   ```
   Shows all processes with their status (running/exited/failed).

3. **View recent output**:
   ```
   supervisor_output(process_id="...", limit=20)
   ```
   Shows the last 20 log entries (stdout/stderr).

4. **Stop when done**:
   ```
   supervisor_stop(process_id="...")
   ```

### Good Use Cases

- **Dev servers**: `npm run dev`, `python manage.py runserver`, `cargo run`
- **File watchers**: `cargo watch -x test`, `nodemon`, `inotifywait` loops
- **Long builds**: `make all`, `cargo build --release`, `docker build`
- **Database/services**: `docker-compose up`, `redis-server`

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
- When a session closes, its processes can be stopped automatically
- The process and its logs are retained after stopping, so you can still query output


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

1. `list_all_bindings(mode="summary")` - Get overview
2. `list_all_bindings(filter="orphaned")` - Find problems
3. `unbind_sessions(orphans_only=true)` - Clean orphans
4. `rebind_session(...)` - Fix specific bindings

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


## MIDI Player

### play_midi
Play musical notes through the browser using Web Audio synthesis.
- `notes` (required): Space-separated note sequence (e.g., "C4 D4 E4:h [C4,E4,G4]:w")
- `bpm` (required): Tempo 60-240
- `waveform` (optional): "sine", "square", "sawtooth", "triangle"
- `volume` (optional): 0-1

Notation: Notes like `C4`, `D#5`, `Eb3`. Durations: `:w` whole, `:h` half, `:q` quarter (default), `:e` eighth, `:s` sixteenth. Rests: `R`. Chords: `[C4,E4,G4]`.
