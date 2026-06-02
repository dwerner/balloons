### start_watching_session

Attach a session as a watcher of a target session.

Use this to create a watch relationship between two sessions. Watching is a relationship, not a special session type: any session can be made to watch a target session.

**Parameters:**
- `session_id`: ID of the session that should become the watcher
- `target_session_id`: ID of the session to watch

**Use cases:**
- Turning an existing session or fork into a watcher
- Attaching a newly created session as a watcher
- Re-attaching a session to observe another session

**Notes:**
- A session cannot watch itself
- If the watch relationship already exists, this is effectively a no-op
- Typical flow: `create_session(...)` then `start_watching_session(...)`
