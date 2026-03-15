# Balloons Profiling Tools

Tools for analyzing performance profiles of the Balloons web UI.

## Quick Start

```bash
# Analyze a Firefox profile
python tools/profiling/analyze_firefox_profile.py <profile.json.gz>

# Copy a profile from a remote machine
scp user@machine:~/Desktop/balloons-profiling/*.json.gz ./
```

## Capturing Profiles

### Firefox Performance Profile (CPU)

1. Open Firefox DevTools (F12)
2. Go to Performance tab
3. Click "Start Recording"
4. Perform the operation (e.g., switch sessions)
5. Click "Stop Recording"
6. Click "Save Profile" (gear icon) → Save as .json

### Firefox Memory Snapshot

For memory issues (leaks, high usage):

1. Open Firefox DevTools (F12)
2. Go to Memory tab
3. Click "Take Snapshot"
4. Perform operation
5. Click "Take Snapshot" again
6. Compare snapshots to find retained objects

### Chrome DevTools

1. Open DevTools (F12)
2. Performance tab → Record
3. Or Memory tab → Heap snapshot

## Analysis Scripts

### `analyze_firefox_profile.py`

General purpose Firefox profile analyzer.

```bash
python analyze_firefox_profile.py profile.json.gz
```

Shows: Thread overview, top functions by self/total time, Balloons functions, GC events, memory counters.

### `find_js_hotspots.py`

Find JS functions with highest self-time across all threads.

```bash
python find_js_hotspots.py profile.json.gz
```

### `find_allocation_sources.py`

Find which JS functions are causing memory allocations.

```bash
python find_allocation_sources.py profile.json.gz
```

### `categorize_time.py`

Categorize CPU time by source (Balloons app, React internals, DevTools, etc.)

```bash
python categorize_time.py profile.json.gz
```

### `trace_stack.py`

Trace stack for a specific function to understand call context.

```bash
python trace_stack.py profile.json.gz addObjectDiffToProperties
```

### Programmatic Use

```python
from analyze_firefox_profile import FirefoxProfile

profile = FirefoxProfile.load('profile.json.gz')

# Get function times
func_times = profile.calculate_function_times(thread_idx=0)
for idx, ft in func_times.items():
    if ft.is_js and ft.self_time_ms > 10:
        print(f"{ft.name}: {ft.self_time_ms}ms")

# Get GC events
for gc in profile.get_gc_events()[:5]:
    print(f"GC: {gc['duration_ms']}ms")

# Find Balloons functions
for idx, name, resource in profile.find_balloons_functions():
    print(f"{name} from {resource}")
```

## Profile Storage

Profiles are stored in `~/Desktop/balloons-profiling/` on the living room machine.

```bash
# List profiles
ssh dan@living-room "ls -la ~/Desktop/balloons-profiling/"

# Copy latest
scp dan@living-room:~/Desktop/balloons-profiling/*.json.gz ./
```

## Known Performance Areas

### Session Switching
- Zustand store updates
- HierarchyView re-renders
- WebSocket message handling

### Memory Issues
- Turn accumulation in long conversations
- React component state retention
- WebSocket message buffers

### Things to Profile
- Session switching (changing active session)
- Long conversation scrolling
- Fork/merge operations
- Search/filtering
- Initial load with many sessions

## Key Finding: React Development Mode

React's development build includes heavy instrumentation that runs on every render:
- `addObjectDiffToProperties` - diffs component props/state
- `addValueToProperties` - tracks values for DevTools
- `logComponentRender` - logs render info

These run **even without React DevTools extension installed** because they're
bundled into `react-dom-client.development.js`.

To test production performance, set in dev-server.ts:
```javascript
define: {
  "process.env.NODE_ENV": '"production"',
},
```
