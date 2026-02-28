## Debug Logging

Balloons has a shared debug logging system that spans both client and server:

**Architecture:**
- `core/debug_log.py` - Server-side singleton logger
- `service/debug_log_service.py` - WebSocket API for the UI
- `web/ui/src/utils/debugLog.ts` - Client-side logger that sends to server

**Log files:**
- `~/.balloons/logs/{category}.log` - Category-specific logs (only when categories enabled)
- `~/.balloons/debug/interactions/` - Full interaction dumps on API errors

**Categories:** api, tool, json, process, stream, perf, client

**How it works:**
- All log entries go to the in-memory log (for UI debug pane)
- When you enable specific categories, those entries write to `~/.balloons/logs/{category}.log`
- Category filtering affects both in-memory log and category files
- Use categories for targeted debugging without sifting through everything

**Tailing logs:**
```bash
tail -f ~/.balloons/logs/api.log      # API requests/responses/chunks (when enabled)
tail -f ~/.balloons/logs/tool.log     # Tool execution (when enabled)
tail -f ~/.balloons/logs/json.log     # JSON parsing errors (when enabled)
tail -f ~/.balloons/logs/client.log   # Web UI client logs (when enabled)
```

**From code:**
```python
from core.debug_log import debug_log

# Log at various levels
debug_log.info("Message", category="api", details={"key": "value"})
debug_log.debug("Verbose info", category="tool")
debug_log.trace("Very verbose", category="stream")
debug_log.warning("Something wrong", category="json")
debug_log.error("Failed", category="process")

# Enable specific categories only
debug_log.enable_category("api")
debug_log.set_categories(["api", "tool"])  # Only these
debug_log.clear_categories()  # Log all (default)
```

**From web client:**
```typescript
import { debugLog } from './utils/debugLog';
debugLog('MyComponent', 'Something happened', { data: 123 });
```
