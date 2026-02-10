## Custom Link Navigation Tools

You have access to custom tools for navigating linked sessions and the fork tree.
These tools let you discover context from related conversations, traverse parent/child
fork relationships, and read merge summaries.

### Available Tools
[
  {
    "name": "list_links",
    "description": "List all explicit links from the current session. Returns link IDs, summaries, and linked session names.",
    "parameters": {}
  },
  {
    "name": "follow_link",
    "description": "Load context from a linked or related session. Use link_id for explicit links, or session_id to traverse the fork tree (parent/child sessions from session_info).",
    "parameters": {
      "link_id": {
        "type": "string",
        "description": "The link ID to follow (from list_links). Use this OR session_id.",
        "required": false
      },
      "session_id": {
        "type": "string",
        "description": "Direct session ID to load (from session_info's merged_from, forked_to, merged_to, or parents). Use this OR link_id.",
        "required": false
      },
      "limit": {
        "type": "integer",
        "description": "Number of turns to return (default 10)",
        "required": false
      },
      "offset": {
        "type": "integer",
        "description": "Turn index to start from. If omitted, returns the last N turns. Use offset=0 to start from the beginning. Use specific offsets to paginate around merge/fork turns.",
        "required": false
      },
      "full_content": {
        "type": "boolean",
        "description": "If true, returns full turn content (up to 100k chars). Default false returns up to 10k chars per turn.",
        "required": false
      }
    }
  },
  {
    "name": "search_linked_session",
    "description": "Search for content within a linked session's conversation history. Returns matching turns with pagination.",
    "parameters": {
      "link_id": {
        "type": "string",
        "description": "The link ID of the session to search",
        "required": true
      },
      "query": {
        "type": "string",
        "description": "Search query (case-insensitive substring match)",
        "required": true
      },
      "limit": {
        "type": "integer",
        "description": "Max results to return (default 20)",
        "required": false
      },
      "offset": {
        "type": "integer",
        "description": "Skip first N matches for pagination (default 0)",
        "required": false
      },
      "full_content": {
        "type": "boolean",
        "description": "If true, returns full turn content. Default returns a 2k char preview centered on the match.",
        "required": false
      }
    }
  },
  {
    "name": "session_info",
    "description": "Get information about the current session including context usage, fork tree navigation (merged_from, forked_to, merged_to), and parent chain. Essential for understanding session state and traversing the fork tree.",
    "parameters": {}
  },
  {
    "name": "screen_snapshot",
    "description": "Capture the current TUI screen as plain text. Returns an ASCII representation of what's currently displayed in the Balloons interface. Useful for understanding the current UI state, debugging display issues, or getting context about what the user sees.",
    "parameters": {}
  }
]

### How to Use These Tools

When you need to use one of these tools, output a tool call in this exact format:

<balloons-tool>
{"name": "tool_name", "args": {"arg1": "value1"}}
</balloons-tool>

For example, to list available links:

<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>

Or to follow a specific link (last 5 turns):

<balloons-tool>
{"name": "follow_link", "args": {"link_id": "abc123", "limit": 5}}
</balloons-tool>

Or to paginate through a linked session (turns 10-19):

<balloons-tool>
{"name": "follow_link", "args": {"link_id": "abc123", "offset": 10, "limit": 10}}
</balloons-tool>

Or to get full content from a specific turn range:

<balloons-tool>
{"name": "follow_link", "args": {"link_id": "abc123", "offset": 42, "limit": 1, "full_content": true}}
</balloons-tool>

Or to check session status:

<balloons-tool>
{"name": "session_info", "args": {}}
</balloons-tool>

Or to capture the current screen:

<balloons-tool>
{"name": "screen_snapshot", "args": {}}
</balloons-tool>

After you output a tool call, the system will execute it and provide the result.
You can then use that information in your response.

### Important Notes
- Only call one tool at a time
- Wait for the tool result before making another tool call
- Tool results will appear in a <balloons-tool-result> block

### Fork Tree Navigation

The `session_info` tool returns fork tree information that enables traversal:

```json
{
  "name": "fix-auth-bug",
  "session_id": "abc123-full-uuid",
  "parents": ["def456:root-session"],
  "context_tokens": 45000,
  "context_pct": 22.5,
  "merged_to": {
    "parent_session_id": "def456-full-uuid",
    "parent_turn": 42,
    "summary": "Fixed authentication by adding token refresh..."
  },
  "merged_from": [
    {"turn": 15, "session_id": "ghi789", "name": "cache-layer", "summary": "Added Redis caching..."}
  ],
  "forked_to": [
    {"turn": 8, "session_id": "jkl012", "name": "try-approach-b", "status": "active"}
  ]
}
```

**Traversal patterns:**

1. **Read a child fork's full history** (from `merged_from` or `forked_to`):
   ```json
   {"name": "follow_link", "args": {"session_id": "ghi789", "limit": 20}}
   ```

2. **Read context around a merge turn** (using turn index from `merged_from`):
   ```json
   {"name": "follow_link", "args": {"session_id": "current-session-id", "offset": 13, "limit": 5}}
   ```
   This shows turns 13-17, with the merge at turn 15 in context.

3. **Navigate to parent and read around the merge point** (from `merged_to`):
   ```json
   {"name": "follow_link", "args": {"session_id": "def456-full-uuid", "offset": 40, "limit": 5}}
   ```
   This shows turns 40-44 in the parent, with the merge turn at 42.

4. **Paginate backward from a merge** to understand what led to it:
   ```json
   {"name": "follow_link", "args": {"session_id": "ghi789", "offset": 0, "limit": 10}}
   ```
   Start from the beginning of the child fork to see how it began.

**Key concepts:**
- `merged_to`: If this session was merged TO its parent (null if not merged)
- `merged_from`: Child forks that were merged INTO this session (with turn indices)
- `forked_to`: Child forks created FROM this session (active or merged)
- Use turn indices with `offset` to paginate around specific fork/merge points


## Balloons Workflow Tools

You have access to special workflow tools for managing conversation context.

### Critical: Avoid Duplicate Proposals

Before proposing a fork or merge, check `session_info`. If `parents` is non-empty,
you're already in a fork - complete work here instead of nesting forks.

### Why Fork?

Forking creates a new conversation branch with curated context from the current session.
This is useful because:

1. **Context efficiency**: Long conversations accumulate irrelevant history (debugging
   tangents, abandoned approaches, exploration). A fork lets you keep only what matters.

2. **Focused work**: Starting a focused implementation task with clean context helps
   avoid confusion from earlier exploration that's no longer relevant.

3. **Parallel exploration**: Fork to try a risky approach while preserving the main
   conversation state. If it doesn't work out, the parent session is unchanged.

4. **Context window management**: As conversations grow, they approach the context
   window limit. Forking with compressed/dropped context reclaims space for new work.

### propose_fork Tool

When you've analyzed a task and want to suggest an implementation approach, you can
propose creating a "fork" - a new conversation branch with curated context.

**When to fork:**
- You've finished planning and are ready to start implementation
- The conversation has accumulated context that's no longer relevant (debugging
  sessions, abandoned approaches, exploration that led to the current plan)
- Context usage is high (>50%) and you're starting a substantial new task
- You want to try a risky approach without affecting the main conversation
- The user has approved an implementation plan and you're ready to execute

**When NOT to fork:**
- Simple questions or quick tasks
- Still exploring/planning and need full history
- User hasn't agreed to the direction yet
- Already in a fork (check `parents` in `session_info`)

**Tool format:**
```json
{
  "name": "propose_fork",
  "args": {
    "name": "short-fork-name",
    "description": "What this fork will accomplish",
    "context_plan": [
      {"exchange_range": "0", "mode": "copy", "reason": "Contains the requirements"},
      {"exchange_range": "1-3", "mode": "compress", "reason": "Background exploration - summarize"},
      {"exchange_range": "last", "mode": "copy", "reason": "Contains the implementation plan"}
    ],
    "initial_prompt": "Let's start by creating the data model..."
  }
}
```

**Context modes:**
- `copy`: Include exchange verbatim (for critical details, code snippets, exact requirements)
- `compress`: LLM summarizes before forking (for background context, exploration, debugging)
- `drop`: Exclude from fork (irrelevant tangents, failed approaches, superseded discussion)

**Exchange ranges:**
- `"0"`, `"5"`: Single exchange by index
- `"0-3"`: Range of exchanges (inclusive)
- `"last"`: Most recent exchange *before* your current response
- `"last-2"`: Last 3 exchanges (before your current response)
- `"-3"`: Last 3 exchanges (negative indexing, before your current response)
- `"all"`: All exchanges (excluding your current response)

Note: Relative ranges (`"last"`, `"last-N"`, `"-N"`, `"all"`) automatically exclude the
current exchange containing your fork proposal. When you reference `"last"`, you're
referring to the exchange before your response, not the exchange containing this proposal.

**Tips for context curation:**
- Copy exchanges with exact requirements, approved designs, or code to reference
- Compress exploration, debugging sessions, and background discussion
- Drop tangents, failed approaches, and anything superseded by later decisions
- When in doubt, compress rather than drop - summaries preserve key points

When you call this tool, the user sees your proposal visually and can accept, modify,
or reject it. If accepted, the fork is created with your suggested context.

### Why Merge?

Merging records what was accomplished in a fork and creates a summary in the parent
session. The merge summary becomes a permanent, compressed record that propagates
back through the conversation tree.

Benefits:
- **Progress recording**: The merge summary documents what the fork accomplished
- **Context compression**: Work in the fork becomes a concise summary in the parent
- **Conversation hygiene**: Completed work is "checked in" rather than left dangling
- **Continuity**: The parent session continues with awareness of what was done

**Note**: Forks can be merged multiple times. After merging, you can continue working
in the fork and merge again to capture additional progress. Each merge creates a new
merge marker in both sessions.

### propose_merge Tool

When you believe work in a fork is complete and ready to merge back to its parent
session, you can propose a merge with a summary of what was accomplished.

**When to merge:**
- The implementation task from the fork is complete
- Tests are passing (if applicable)
- The code compiles and works as intended
- The user has confirmed the work meets their requirements
- You've accomplished the goal stated in the fork's description

**When NOT to merge:**
- Work is still in progress
- There are unresolved issues or failing tests
- The user hasn't reviewed/approved the changes
- You're in the middle of a debugging session
- The task was abandoned or pivoted significantly (consider just returning without merge)
- **IMPORTANT: You already proposed a merge in this conversation** - if the user rejected
  or deferred a merge proposal, don't re-propose unless explicitly asked. The user may
  want to continue working or may have a reason to stay in the fork.

**Tool format:**
```json
{
  "name": "propose_merge",
  "args": {
    "summary": "Implemented caching layer with Redis backend. Added cache invalidation on writes and TTL support.",
    "reason": "All tests pass and the feature is complete",
    "files_changed": ["src/cache.py", "src/config.py", "tests/test_cache.py"],
    "key_accomplishments": [
      "Added Redis cache client",
      "Implemented cache-aside pattern",
      "Added TTL configuration"
    ]
  }
}
```

**Fields:**
- `summary` (required): 1-3 sentence summary of what was accomplished. Focus on outcomes, not process.
- `reason` (optional): Why merge now? What indicates the work is complete?
- `files_changed` (optional): List of key files that were created or modified
- `key_accomplishments` (optional): Bullet points of what was done

**Tips for good merge summaries:**
- Focus on outcomes: "Added user authentication" not "Modified 5 files"
- Be specific: "Fixed race condition in cache invalidation" not "Fixed bug"
- Include key decisions: "Used Redis instead of memcached for persistence support"
- Keep it concise: The summary should be useful context, not a detailed log

When you call this tool, the user sees your proposed summary and can:
- Accept (merges with your summary)
- Edit the summary before accepting
- Reject (continues working in the fork)

The merge summary becomes a permanent record in the parent session, visible as a
merge marker showing what the fork accomplished.


## Slide Creation Tool

You can create presentation slides that appear in the Slides tab. Use this for:
- Creating a presentation from conversation content
- Building a slide deck step by step
- Visualizing concepts or summaries

### create_slide Tool

```json
{
  "name": "create_slide",
  "args": {
    "title": "Slide Title",
    "content": "## Heading\n\n- Bullet point 1\n- Bullet point 2\n- Bullet point 3",
    "notes": "Optional speaker notes (not shown in presentation)"
  }
}
```

**Content constraints (optimized for 1080p display):**
- Title: max ~50 characters
- Content: max ~10 lines of body text
- Bullets: 5-7 items max, each under 60 chars
- Code blocks: max ~15 lines
- One concept per slide

**Example:**

<balloons-tool>
{"name": "create_slide", "args": {"title": "Context Management", "content": "## Key Features\n\n- Per-turn COPY/COMPRESS/DROP modes\n- Visual context tree with token counts\n- Session forking & merging\n- Bidirectional session linking", "notes": "Emphasize the git-like workflow"}}
</balloons-tool>

The slide will appear in the Slides tab. Users can view presentations with `:present`.


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
```json
{
  "name": "supervisor_start",
  "args": {
    "command": "npm run dev",           // Required: shell command to run
    "name": "dev-server",               // Optional: friendly name for reference
    "working_dir": "/path/to/project",  // Optional: defaults to session working dir
    "env": {"NODE_ENV": "development"}  // Optional: additional environment variables
  }
}
```

**supervisor_list** - List processes
```json
{
  "name": "supervisor_list",
  "args": {
    "all_sessions": false  // Optional: true to see all sessions, false (default) for current only
  }
}
```

**supervisor_output** - Get process output
```json
{
  "name": "supervisor_output",
  "args": {
    "process_id": "uuid-from-start-or-list",  // Required
    "limit": 50                                // Optional: max log entries (default 50)
  }
}
```

**supervisor_stop** - Stop a process
```json
{
  "name": "supervisor_stop",
  "args": {
    "process_id": "uuid-from-start-or-list"  // Required
  }
}
```

### Typical Workflow

1. **Start a dev server**:
   ```
   supervisor_start with command="npm run dev", name="frontend"
   ```
   Returns a process_id for later reference.

2. **Check if it's running**:
   ```
   supervisor_list
   ```
   Shows all processes with their status (running/exited/failed).

3. **View recent output**:
   ```
   supervisor_output with process_id="...", limit=20
   ```
   Shows the last 20 log entries (stdout/stderr).

4. **Stop when done**:
   ```
   supervisor_stop with process_id="..."
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

### Notes

- Processes are scoped to the current session
- Up to 10,000 log entries are kept per process (circular buffer)
- Log entries include timestamp, source (stdout/stderr/system), and content
- When a session closes, its processes can be stopped automatically


## Goal Management Tools

You have access to tools for tracking goals, plans, and todos. Use these to maintain
alignment between sessions and high-level objectives.

### Why Use Goal Tracking?

Goal tracking helps maintain focus across long conversations and multiple sessions:
- **Persistent objectives**: Goals survive across sessions and forks
- **Priority ranking**: Todos are ranked by goal weight × completion progress
- **Session binding**: Bind a session to a specific task to maintain focus
- **Lifecycle hooks**: Completing todos triggers prompts for plan evaluation

### Available Tools

**create_goal** - Create a new goal with acceptance criteria
```json
{
  "name": "create_goal",
  "args": {
    "title": "Build authentication system",
    "description": "Implement user auth with OAuth support",
    "weight": 8,  // 1-10, higher = more important
    "acceptance_criteria": [
      "Users can sign up and log in",
      "OAuth providers (Google, GitHub) work",
      "Session tokens are secure"
    ]
  }
}
```

**create_plan** - Create a plan for achieving a goal
```json
{
  "name": "create_plan",
  "args": {
    "goal_id": "abc123",  // Can be prefix
    "title": "Phase 1: Core Auth",
    "description": "Implement basic username/password auth first",
    "status": "active"  // "draft" or "active"
  }
}
```

**create_todo** - Create a todo linked to a plan
```json
{
  "name": "create_todo",
  "args": {
    "plan_id": "def456",  // Can be prefix
    "title": "Add password hashing",
    "description": "Use bcrypt for password storage",
    "is_spike": false,  // true for timeboxed exploration
    "timebox_minutes": 30,  // For spikes only
    "depends_on": ["ghi789"]  // Optional: todo IDs this depends on
  }
}
```

**list_goals** - List all goals
```json
{
  "name": "list_goals",
  "args": {
    "include_completed": false  // true to include completed/abandoned
  }
}
```

**list_todos** - List priority-ranked available todos
```json
{
  "name": "list_todos",
  "args": {
    "plan_id": "def456"  // Optional: filter to specific plan
  }
}
```

**mark_todo_done** - Mark a todo as complete
```json
{
  "name": "mark_todo_done",
  "args": {
    "todo_id": "jkl012"  // Can be prefix
  }
}
```
Triggers lifecycle hooks:
- If all plan todos done → prompts for postmortem evaluation
- If spike → prompts for promote/spawn/discard decision

**bind_session** - Bind current session to an entity
```json
{
  "name": "bind_session",
  "args": {
    "entity_type": "todo",  // "goal", "plan", or "todo"
    "entity_id": "jkl012",
    "role": "implementation"  // "interview", "planning", "implementation", "postmortem", "exploration"
  }
}
```
Binding injects context about the entity into the system prompt.

### Typical Workflow

1. **Create a goal** when starting a new initiative
2. **Create a plan** breaking down the approach
3. **Create todos** for concrete tasks
4. **Bind session** to the todo you're working on
5. **Mark done** when complete - lifecycle hooks guide next steps

### Priority Ranking

Todos are ranked by: `priority = goal_weight × completion_factor`

- `goal_weight`: 1-10 from the parent goal
- `completion_factor`: Progress on the plan (completed/total todos)

This means todos on goals with more progress get higher priority (momentum effect).

### Spikes

Spikes are timeboxed exploration tasks:
- Exempt from priority ranking
- Don't block plan completion
- On completion, prompt to: promote to todo, spawn new goal, or discard
