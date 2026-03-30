### ask_user

Stop and ask the user a question, waiting for their response.

**When to use:**
- Need clarification about requirements or preferences
- Want confirmation before a significant action (deleting files, major refactors)
- Unsure which approach the user prefers
- Need additional information to proceed

**When NOT to use:**
- Rhetorical questions in your response text
- Status updates (just write them in your response)
- Questions you can answer yourself from context

**IMPORTANT:** This tool **stops** the agentic loop. Do not continue generating tool calls after `ask_user` - wait for the user's response.
