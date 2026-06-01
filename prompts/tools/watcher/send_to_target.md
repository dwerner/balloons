### send_to_target

Send a message to the target session you're watching. The message is queued and delivered when the target completes its current exchange.

Prefer this for brief guidance to the existing watched session.
If you need a separate watcher with its own focused role or prompt, use `create_watched_session` instead.

**Use cases:**
- Suggesting an alternative approach when the target seems stuck
- Providing a reminder about user instructions
- Sharing relevant context the target might have missed
