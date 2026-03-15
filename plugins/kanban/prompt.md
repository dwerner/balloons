## Kanban Board Tools

You have access to kanban board tools for tracking tasks within sessions. The kanban
system is lighter-weight than goals/plans/todos - use it for quick task tracking that
doesn't need the full goal hierarchy.

### When to Use Kanban vs Goals

**Use Kanban when:**
- Quick task lists for the current session
- Tracking small items during a conversation
- User wants a simple visual board
- Tasks don't need dependencies or hierarchy

**Use Goals/Plans/Todos when:**
- Multi-session work that needs to persist
- Complex task hierarchies with dependencies
- Tracking progress across multiple conversations
- Need priority ranking and lifecycle management

### Available Tools

**kanban_get_boards** - List boards associated with this session
```json
{"name": "kanban_get_boards", "args": {}}
```

**kanban_create_board** - Create a new board for this session
```json
{"name": "kanban_create_board", "args": {"name": "Sprint 1"}}
```

**kanban_create_task** - Create a task (goes to Backlog by default)
```json
{"name": "kanban_create_task", "args": {"title": "Implement feature X", "description": "Details..."}}
```

**kanban_move_task** - Move task to a different column (use names, not IDs)
```json
{"name": "kanban_move_task", "args": {"task": "Implement feature X", "to_column": "In Progress"}}
```

**kanban_update_task** - Update task title, description, or resolution
```json
{"name": "kanban_update_task", "args": {"task_id": "...", "title": "New title"}}
{"name": "kanban_update_task", "args": {"task_id": "...", "resolution": "Added caching layer with Redis"}}
```

**kanban_delete_task** - Remove a task
```json
{"name": "kanban_delete_task", "args": {"task_id": "..."}}
```

**kanban_list_tasks** - List all tasks on the board
```json
{"name": "kanban_list_tasks", "args": {}}
```

**kanban_get_board_state** - Get full board with all columns and tasks
```json
{"name": "kanban_get_board_state", "args": {}}
```

### Kanban Workflow

When working with tasks on a kanban board, follow this workflow:

1. **Check the board** at the start of work:
   - Use `session_info` to see current board state in the `boards` field
   - Review what's in each column

2. **Move tasks as you work**:
   - When starting a task: `kanban_move_task(task="...", to_column="In Progress")`
   - When completing: `kanban_move_task(task="...", to_column="Done")`
   - When blocked: `kanban_move_task(task="...", to_column="Backlog")` with a note

3. **Write resolutions when completing tasks**:

   Resolutions are the most valuable part of a kanban task. They capture what was
   actually done, learned, or decided - turning ephemeral work into permanent knowledge.

   **When to write a resolution:**
   - Before or immediately after moving a task to Done
   - When abandoning a task (document why)
   - When a task reveals something unexpected

   **What to include in a resolution:**
   - **What was done**: Concrete actions taken, files changed, decisions made
   - **Key insights**: Anything learned that wasn't obvious at the start
   - **Gotchas**: Problems encountered and how they were solved
   - **Links**: References to commits, PRs, docs, or other resources
   - **Follow-ups**: Any spawned work or open questions

   **Resolution quality guidelines:**
   - Write for your future self who has forgotten the context
   - Be specific: "Fixed race condition in cache invalidation by adding mutex"
     not "Fixed bug"
   - Include the "why" when it's not obvious
   - For exploration tasks, summarize findings even if inconclusive
   - Keep it concise but complete - 2-5 sentences is often right

4. **Keep the board current**:
   - Create tasks for new work items as they come up
   - Move tasks to Done when complete
   - Don't let In Progress accumulate - finish or move back

5. **Standard columns**:
   - **Backlog**: Work not yet started
   - **To Do**: Ready to work on
   - **In Progress**: Currently being worked on
   - **Done**: Completed

### Tips

- You can use task titles instead of IDs: `kanban_move_task(task="my task", ...)`
- You can use column names instead of IDs: `to_column="Done"` (case-insensitive)
- The board state appears in `session_info` output under `boards`
- Tasks include `id`, `title`, `description`, `resolution`, `created_at`, `updated_at`
