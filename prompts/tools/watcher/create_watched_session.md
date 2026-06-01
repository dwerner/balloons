### create_watched_session

Create a new watcher session for the same target session you are currently watching.

Use this when a separate watcher session would be better than sending a quick note with `send_to_target`.
For example, create a dedicated watcher with a specialized monitoring role, narrower review criteria, or a clean prompt focused on one concern.

**Parameters:**
- `prompt` (optional): Initial instructions for the new watcher session

**Use cases:**
- Creating a specialist watcher focused only on tests, performance, or security
- Starting a clean watcher thread with a more specific review brief
- Splitting watcher responsibilities instead of overloading the current watcher

**Prefer `send_to_target` when:**
- You only need to send a short suggestion or reminder to the current target
- No separate watcher session is necessary
