# UI Thread Blocking Calls Audit

**Date:** 2025-02-13
**Scope:** Identify all blocking calls from UI thread to network/storage
**Status:** Spike - 60 min timeboxed exploration

## Executive Summary

Found **17 blocking call sites** across 5 severity categories. Most critical are sync file I/O in UI handlers and missing import causing runtime errors in `sounds.py`.

---

## Critical (P0) - Runtime Errors or Severe Blocking

### 1. `core/sounds.py:20` - Missing subprocess import
**Severity:** CRITICAL (Runtime Error)

```python
def _find_player() -> Optional[str]:
    result = subprocess.run(  # NameError: 'subprocess' not defined
        ["which", player],
        capture_output=True,
        text=True,
    )
```

**Issue:** `subprocess` is not imported at the top of the file. This will cause a `NameError` when `_find_player()` is called from `play_sound_async()`.

**Called from:** `play_sound_async()` → `play_sound()` → `play_done_sound()`, `play_error_sound()`, `play_notification_sound()` (all called from UI handlers)

**Fix:** Add `import subprocess` at module top.

---

### 2. `core/sounds.py:20-28` - Blocking subprocess in async path
**Severity:** HIGH

```python
async def play_sound_async(sound_name: str) -> None:
    # ...
    player = _find_player()  # BLOCKS - calls subprocess.run()
```

**Issue:** `_find_player()` uses `subprocess.run()` synchronously within an async function, blocking the event loop while checking for audio players.

**Fix:** Cache the player result on first call, or use `asyncio.create_subprocess_exec` to find the player.

---

### 3. `core/stash.py:63-66` - Sync file read in __init__
**Severity:** HIGH

```python
def _load(self) -> None:
    """Load stash from file (sync, used at init)."""
    if self._stash_file.exists():
        with open(self._stash_file) as f:
            data = yaml.safe_load(f) or {}
```

**Called from:** `MessageStash.__init__()` which is called during `BalloonsApp.__init__()` (line 347)

**Impact:** Blocks app startup while reading stash file. YAML parsing is also CPU-bound.

**Fix:** Defer loading until first access, or make async.

---

## High (P1) - Blocking in UI Event Handlers

### 4. `app.py:4464` - Sync file I/O in rehydrate handler
**Severity:** HIGH

```python
async def on_archive_marker_rehydrate_requested(self, event):
    new_turns = archiver.rehydrate(self.session.turns, event.turn_index)  # BLOCKS
```

**Issue:** `archiver.rehydrate()` calls `load_archive()` which uses `Path.read_text()` to read JSON from disk.

**Fix:** Use `archiver.rehydrate_async()` instead.

---

### 5. `core/command_executor.py:257` - Sync file I/O in command handler
**Severity:** HIGH

```python
def prepare_rehydrate(self, session, turn_index):
    new_turns = archiver.rehydrate(session.turns, turn_index)  # BLOCKS
```

**Issue:** Same as #4 - sync file read in command executor.

**Fix:** Make `prepare_rehydrate()` async and use `archiver.rehydrate_async()`.

---

### 6. `config.py:86` - Sync file read for system prompt
**Severity:** HIGH

```python
def load_system_prompt(self) -> Optional[str]:
    if path.exists():
        self._system_prompt_content = path.read_text()  # BLOCKS
```

**Called from:** `create_runner()` via `backend.load_system_prompt()` which is called from `_create_session_runner()` (app.py:159)

**Fix:** Use `load_system_prompt_async()` which exists but isn't being used in all paths.

---

### 7. `config.py:240, 307, 315` - Sync file I/O in Config.load()/save()
**Severity:** HIGH

```python
@classmethod
def _load_from_file(cls, path: Path) -> "Config":
    with open(path) as f:  # BLOCKS
        data = yaml.safe_load(f) or {}

def save(self) -> None:
    with open(path) as f:  # BLOCKS
        data = yaml.safe_load(f) or {}
    with open(path, "w") as f:  # BLOCKS
        yaml.safe_dump(data, f)
```

**Called from:** `get_config()` (module-level), `save_last_view()` (app.py:2438, 4673, 5095, 5217)

**Fix:** Use `Config.load_async()` and `Config.save_async()` which exist but aren't being used consistently.

---

### 8. `app.py:611` - Sync file I/O in on_mount
**Severity:** MEDIUM-HIGH

```python
async def on_mount(self) -> None:
    ensure_prompts_installed()  # BLOCKS
```

**Issue:** `ensure_prompts_installed()` uses `Path.exists()`, `Path.mkdir()`, `Path.read_text()`, `Path.write_text()` - all blocking.

**Fix:** Create async version `ensure_prompts_installed_async()`.

---

## Medium (P2) - Blocking in Widget Methods

### 9. `widgets/context_tree.py:1701` - Sync token counting in add_turn
**Severity:** MEDIUM

```python
def add_turn(self, session_id, role, content, content_block):
    tokens = count_tokens(content) if content else 0  # BLOCKS
```

**Issue:** `count_tokens()` is CPU-bound and blocks the UI thread. The Rust tokenizer releases GIL but still takes time.

**Called from:** Streaming turn updates

**Fix:** Use `AsyncTokenizer.count_tokens_deferred()` with callback, or skip token counting during streaming and update later.

---

### 10. `widgets/context_preview.py:170` - Sync token counting in compose
**Severity:** MEDIUM

```python
def compose(self) -> ComposeResult:
    token_count = count_tokens(context)  # BLOCKS
```

**Issue:** Token counting blocks dialog open. Context can be large.

**Fix:** Show dialog immediately with "Calculating..." then update asynchronously.

---

### 11. `core/binding_context.py:60-61` - Sync file read (cached)
**Severity:** LOW-MEDIUM

```python
def _load_role_guidance(role: str) -> str:
    if role_file.exists():
        content = role_file.read_text()  # BLOCKS (first call only)
```

**Mitigation:** Results are cached in `_role_guidance_cache`, so only blocks on first call per role.

**Fix:** Pre-load at startup or make async.

---

## Low (P3) - Sync Patterns with Async Alternatives

### 12. `core/archiver.py:404-408, 497, 512-516` - Sync read_text() in load_archive
**Severity:** LOW (async version exists)

```python
def load_archive(self, archive_block):
    data = json.loads(file_path.read_text())  # BLOCKS
```

**Note:** Async version `load_archive_async()` exists (line 606) but callers sometimes use sync version.

---

### 13. `core/runner_factory.py:74` - Sync read_text() for prompts
**Severity:** LOW

```python
def _load_prompt_file(filename: str) -> str:
    return path.read_text()  # BLOCKS
```

**Called from:** `create_runner()` during session initialization.

**Fix:** Cache at startup or make async.

---

### 14. `core/summarizer.py:35` - Sync read_text() for summary prompt
**Severity:** LOW

```python
def _get_sync_link_summary_prompt() -> str:
    return _LINK_SUMMARY_PROMPT_PATH.read_text()  # BLOCKS
```

**Note:** Called from `_get_link_summary_prompt()` which is async but falls back to sync.

---

## Informational - Properly Handled

### Already Async/Offloaded (Good Examples)

1. **`core/async_storage.py`** - Uses `ThreadPoolExecutor` for LMDB operations ✓
2. **`core/async_tokenizer.py`** - Uses `ThreadPoolExecutor` for token counting ✓
3. **`core/archiver.py:537+`** - Async versions exist for all file operations ✓
4. **`core/debug_log.py:140`** - Uses `aiofiles` for log writes ✓
5. **`core/stash.py:78`** - Uses `aiofiles` for stash saves (but not loads) ✓

---

## Summary by Category

| Category | Count | Files Affected |
|----------|-------|----------------|
| Critical (Runtime Error) | 1 | sounds.py |
| High (UI Handler Blocking) | 5 | app.py, command_executor.py, config.py, sounds.py, stash.py |
| Medium (Widget Blocking) | 3 | context_tree.py, context_preview.py, binding_context.py |
| Low (Async Alternative Exists) | 4 | archiver.py, runner_factory.py, summarizer.py |

---

## Recommended Fix Priority

1. **Immediate:** Fix missing `import subprocess` in `sounds.py`
2. **High:** Add async path for `_find_player()` in `sounds.py`
3. **High:** Change `on_archive_marker_rehydrate_requested` to use async rehydrate
4. **High:** Make `MessageStash._load()` async or deferred
5. **Medium:** Use `Config.load_async()` and `save_async()` consistently
6. **Medium:** Use `AsyncTokenizer` in widgets instead of sync `count_tokens()`
7. **Low:** Pre-load prompt files at startup

---

## Notes

- The codebase has good async patterns established (`AsyncStorage`, `AsyncTokenizer`, `aiofiles`)
- Issues are mostly in older code or edge cases not yet migrated to async
- `sounds.py` is completely broken due to missing import - easy fix but needs test coverage
