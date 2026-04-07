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

**Example:**
```json
{
  "name": "implement-cache-layer",
  "description": "Add Redis caching to the API endpoints",
  "context_plan": [
    {"exchange_range": "0-2", "mode": "compress", "reason": "Background discussion"},
    {"exchange_range": "last", "mode": "copy", "reason": "Implementation requirements"}
  ]
}
```

The user will see a visual proposal and can accept, modify, or reject.
