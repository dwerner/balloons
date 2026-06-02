### stop_watching_session

Stop a session from watching one or more target sessions.

Use this to remove an existing watch relationship. If `target_session_id` is omitted, the session stops watching all current targets.

**Parameters:**
- `session_id`: ID of the session that is currently watching
- `target_session_id` (optional): specific watched target to stop watching; omit to stop watching all targets
- `reason` (optional): why watching stopped. Defaults to `user`

**Use cases:**
- Detaching a watcher from a specific target
- Stopping all watch relationships for a session
- Cleaning up a watch relationship after a monitoring task is done

**Notes:**
- This changes the watch relationship; it does not delete either session
- Typical reasons include `user`, `session_closed`, or `session_archived`
