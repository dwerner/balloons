### propose_fork

Propose creating a new conversation branch with curated context.

**When to use:**
- Finished planning and ready to start implementation
- Conversation has accumulated irrelevant context (debugging, abandoned approaches)
- Context usage is high (>50%) and starting a substantial new task

**Context plan modes:**
- `copy`: Include exchange verbatim
- `compress`: LLM summarizes the exchange
- `drop`: Exclude from fork

**Exchange ranges:** `"0-2"` (indices), `"5"` (single), `"last"` (most recent), `"-3"` (last 3), `"all"`

**Backend selection:** Use `backend_name` to specify a different model/backend for the fork (e.g., "claude", "openrouter"). If not specified, the fork inherits the parent session's backend.

The user will see a visual proposal and can accept, modify, or reject.
