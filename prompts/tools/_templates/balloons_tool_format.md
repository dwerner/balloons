## How to Call Balloons Tools

For Balloons-specific tools (propose_fork, propose_merge, list_links, follow_link, search_linked_session, session_info, ask_user, and domain plugin tools), you must use the `<balloons-tool>` XML format.

**CRITICAL: Output the XML directly as raw text - do NOT wrap in code blocks (triple backticks).**

Format:
<balloons-tool>
{"name": "tool_name", "args": {"arg1": "value1", "arg2": "value2"}}
</balloons-tool>

**Examples:**

To propose a fork:
<balloons-tool>
{"name": "propose_fork", "args": {"name": "implement-feature", "description": "Implement the new feature", "context_plan": [{"exchange_range": "0-2", "mode": "compress", "reason": "Background"}, {"exchange_range": "last", "mode": "copy", "reason": "Recent details"}]}}
</balloons-tool>

To list session links:
<balloons-tool>
{"name": "list_links", "args": {}}
</balloons-tool>

To get session info:
<balloons-tool>
{"name": "session_info", "args": {}}
</balloons-tool>

**Important:**
- Only call one Balloons tool at a time
- Wait for the tool result before making another call
- Results appear in `<balloons-tool-result>` blocks
- Standard file tools (Read, Write, Edit, Bash, Glob, Grep) use normal function calling - NOT this format
