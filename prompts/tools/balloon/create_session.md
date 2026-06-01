### create_session

Create a new session.

Use this when you need a fresh session that is not a fork. This is a general session-management primitive and can be combined with other tools such as `start_watching_session` to make the new session watch a target.

**Parameters:**
- `working_directory` (optional): Working directory for the new session. Defaults to the current session's working directory when omitted.

**Use cases:**
- Starting a fresh thread for a different subtask
- Creating a session that can later be attached as a watcher
- Spinning up a clean session without parent/fork relationships
