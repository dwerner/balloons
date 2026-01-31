# Context Tree & Fork/Merge Rework Plan

## Core Mental Model

### Session Hierarchy

Sessions form a tree structure with forks and merges:

```
Main Session
├── 💬 chat
├── 💬 chat
├── 🔀 Fork: auth-bug
│   ├── 💬 [child work...]
│   ├── 🔀 Fork: deep-dive (nested)
│   │   └── 💬 [nested work...]
│   │   └── ⬅️ Merged: "found root cause"
│   └── ⬅️ Merged: "JWT validation fix"
├── 💬 chat (continued while forks active)
├── 🔀 Fork: perf-issue [active]
│   └── 💬 [still working...]
├── ⬅️ Merge point: auth-bug results appear here
├── 💬 chat
└── 💬 chat
```

### Key Concepts

**Fork** = Child session to explore a tangent
- User controls what context the child inherits (via tree selection)
- Child works independently
- Parent can continue chatting while forks are active
- Multiple concurrent forks allowed

**Merge** = Bring results back to parent
- User writes the merge message (`:merge The fix was...`)
- Merge is final - fork becomes read-only
- Parent receives the merge message as a new turn
- To do more on the topic, start a new fork

**View = Chat target**
- Wherever you're viewing, that's where input goes
- Breadcrumb shows current position in hierarchy
- Click tree or breadcrumb to navigate

---

## Commands

| Command | Description |
|---------|-------------|
| `:new` | Blank new session |
| `:derive` | New independent session with selected context (no parent link) |
| `:fork <prompt>` | Create child fork, switch to it |
| `:fork=name <prompt>` | Create named fork |
| `:merge <message>` | Return to parent with summary (required message) |
| `:switch [name]` | Switch view to a fork/session (picker if no name) |

### Fork Behavior

```bash
:fork investigate the auth bug          # anonymous fork
:fork=auth-bug investigate the auth bug  # named fork for easy reference
```

**What the fork inherits** (controlled by tree selection before forking):
- ✓ COPY: Full content goes to child
- Σ COMPRESS: LLM summarizes before child starts
- ✗ DROP: Not included

### Merge Behavior

```bash
:merge The auth bug was in the JWT validation, fixed by...
```

- Message is required (no auto-summary for now)
- Creates merge turn in parent
- Switches view back to parent
- Fork status changes to `[merged ✓]`
- Fork becomes read-only

---

## Tree Structure

### Forks Inline with Turns

Forks appear as entries in the parent session's turn list:

```
📁 Sessions
├── 📄 Main Session
│   ├── 💬 User: help me debug
│   ├── 💬 Assistant: I'll look into...
│   ├── 🔀 auth-bug [active]
│   │   ├── 💬 User: check the middleware
│   │   ├── 💬 Assistant: Found it...
│   │   └── 🔀 deep-dive [merged ✓]
│   ├── 🔀 perf-issue [active]
│   ├── ⬅️ Merge: auth-bug → "The bug was..."
│   ├── 💬 User: great, now...
│   └── 💬 Assistant: ...
├── 📄 Other Session
└── 📄 Derived: "API work" (from Main)
```

### Status Indicators

- `[active]` - fork in progress
- `[merged ✓]` - completed and merged back
- `[abandoned]` - never merged (user left it)

---

## Navigation

### Breadcrumb

Header bar above chat shows current location:

```
Main Session                              # top-level
Main Session > auth-bug                   # in a fork
Main Session > auth-bug > deep-dive       # nested fork
Derived: "API refactor" (from Main)       # derived session
```

Each segment is clickable to navigate up.

### Switching

1. **Click tree node** → switch to that session/fork
2. **Click breadcrumb segment** → navigate up
3. **`:switch name`** → switch to named fork
4. **`:switch`** → show picker of available forks

---

## Context Modes (for Fork Preparation)

The three modes control what context a fork inherits:

| Mode | Icon | Effect at Fork |
|------|------|----------------|
| COPY | ✓ | Include verbatim |
| COMPRESS | Σ | LLM summarizes first |
| DROP | ✗ | Exclude entirely |

**Important**: Modes only affect forking, not regular prompts.
- Regular prompts always use full session history
- No accidental context loss from selection

### Status Bar Shows Fork Context

```
Fork context: 5 turns (3 copy, 2 compress) ~2.1k tokens
```

When nothing specifically selected:
```
Fork context: full session (12 turns) ~8.3k tokens
```

---

## Implementation Status

### Phase 1: Core Command Rework ✅ DONE

1. **Rename `:with` → `:fork`** ✅
   - Added `=name` syntax for named forks (`:fork=auth-bug prompt`)
   - Keep context mode handling (COPY/COMPRESS/DROP)
   - Legacy `:with` and `:with-copy` still work

2. **Rename `:return` → `:merge`** ✅
   - Message is required (`:merge Fixed the bug by...`)
   - Marks fork as merged and read-only
   - Legacy `:return` still works

3. **Legacy commands preserved** ✅
   - `:with-copy` still works
   - Can be removed later if desired

4. **Add `:derive` command** ✅
   - Creates independent session with selected context
   - No parent relationship - won't merge back

5. **Add `:switch` command** ✅
   - `:switch name` switches to named fork
   - `:switch` (no arg) lists available forks
   - `:switch parent` or `:switch ..` goes to parent

### Phase 2: Tree Structure Changes ✅ DONE

1. **Display forks inline with turns** ✅
   - Fork nodes appear at fork_point in parent session
   - Nested forks shown as children
   - Merge entries appear at merge_point

2. **Show fork status badges** ✅
   - `[active]` - fork in progress
   - `[merged ✓]` - completed and merged

3. **Track fork metadata** ✅
   - New Session fields: fork_name, fork_status, fork_point_turn, merge_point_turn, merge_message
   - Child records track: name, fork_point, merge_point

### Phase 3: Breadcrumb Navigation ✅ DONE

1. **Add breadcrumb widget above chat** ✅
   - Shows path: `Main Session > auth-bug > deep-dive`
   - Hidden when at top-level session
   - Shows [merged] indicator for read-only forks

2. **Update tree click handling** ✅
   - Clicking fork/merge nodes navigates there
   - Updates breadcrumb to match

3. **Navigation options** ✅
   - Click breadcrumb to go to parent
   - `:switch parent` command
   - Click tree nodes

### Phase 4: Polish ✅ DONE

1. **Rename SUMMARIZE → COMPRESS** ✅
   - COMPRESS is now the primary name
   - SUMMARIZE kept as alias for backwards compat
   - Tree cycles: COPY → COMPRESS → DROP

2. **New widgets** ✅
   - ForkMarker: shows fork start in chat
   - MergeMarker: shows merge result in chat
   - Breadcrumb: shows hierarchy path

---

## Still TODO

1. **Picker UI for `:switch`**
   - Currently just lists forks in status bar
   - Could add modal picker

2. **Keyboard shortcut for fork**
   - `F` in tree to fork with current selection

3. **Status bar improvements**
   - Show fork context stats
   - Indicate when in a fork vs top-level

---

## Open Questions

1. **Derive vs Fork naming** - Is `:derive` the right name for "new session from context"?

2. **Cross-session context** - Can you fork with context from multiple sessions?
   - Current behavior allows this
   - Might be confusing with new hierarchy model

3. **Fork from any point** - Can you fork from a historical turn (not just current end)?
   - Would enable "what if we'd done this differently"
   - Adds complexity

4. **Re-fork from merged** - Can you start a new fork from a merged fork's final state?
   - Useful for "continue that line of thought"
   - The merged fork is read-only, but you could fork from it

---

## What's NOT Changing

- Regular prompts use full session history (no context filtering)
- `:new` creates blank session
- Session persistence to JSON files
- Basic tree selection (COPY/COMPRESS/DROP cycling)
