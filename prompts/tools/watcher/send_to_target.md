### send_to_target

Send a message to the target session you're watching. The message is queued and delivered when the target completes its current exchange.

Prefer this for brief guidance to the existing watched session.
If you need a separate session for a different role or strategy, create a new session and then use `start_watching_session` to attach it.

**Use cases:**
- Suggesting an alternative approach when the target seems stuck
- Providing a reminder about user instructions
- Sharing relevant context the target might have missed
