# Mobile Changes View - MVP Plan

**Goal**: Review what an AI coding agent has changed during a session, from your phone.

**Primary Use Case**: You've kicked off a coding task with Claude, stepped away from your desk, and want to check what it's done so far. Pull out your phone, see the diff, understand the changes.

**Why mobile-first?** This view is specifically for the web UI where you're likely on a phone reviewing agent work remotely. The goal is fast read-only inspection of agent-generated changes away from your desk.

## User Story

> "I asked Claude to refactor the auth module. I'm on the train now and want to see what it changed before I get back to my desk. I open Balloons on my phone, tap the Changes tab, and can scroll through the diffs to understand what Claude did."

## Key Considerations

- **Multiple sessions, one working directory**: You might have several Balloons sessions working on the same repo. The Changes view shows the combined unstaged changes—it's a view of the working directory, not tied to "what this session changed."
- **Review, not action**: MVP is read-only. You're catching up on what happened, not trying to stage/commit from mobile (that's awkward anyway).
- **Agent-generated code**: The changes are typically from an AI agent, so they might be large or span many files. Good navigation is key.

## Scope (MVP)

- **Read-only** - no staging, unstaging, or committing
- **Unstaged changes only** - what `git diff` shows (what the agent wrote but hasn't committed)
- **Session's working directory** - uses the directory the session is attached to
- **Mobile-first UI** - designed for touch, vertical scrolling, easy file navigation

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Web UI (React/TS)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │              ChangesView Component                │  │
│  │  - File list with change indicators               │  │
│  │  - Expandable diff viewer                         │  │
│  │  - Pull-to-refresh                                │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                              │
│                    WebSocket API                        │
└──────────────────────────┼──────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────┐
│                 balloons-browser (Rust)                 │
│  ┌───────────────────────────────────────────────────┐  │
│  │              GitChanges Module                    │  │
│  │  - get_unstaged_changes(path) -> Vec<FileDiff>    │  │
│  │  - Parse unified diff format                      │  │
│  │  - Return structured diff data                    │  │
│  └───────────────────────────────────────────────────┘  │
│                          │                              │
│                    git2 crate                           │
└─────────────────────────────────────────────────────────┘
```

## Backend (Rust)

### Location
`balloons-rs/crates/balloons-browser/src/git_changes.rs`

### Data Structures

```rust
#[derive(Serialize)]
pub struct ChangesResponse {
    pub working_dir: String,
    pub files: Vec<FileDiff>,
    pub stats: ChangeStats,
}

#[derive(Serialize)]
pub struct FileDiff {
    pub path: String,
    pub status: FileStatus,  // Modified, Added, Deleted, Renamed
    pub hunks: Vec<Hunk>,
    pub stats: FileStats,    // lines added/removed
}

#[derive(Serialize)]
pub struct Hunk {
    pub header: String,      // @@ -1,3 +1,4 @@
    pub old_start: u32,
    pub old_lines: u32,
    pub new_start: u32,
    pub new_lines: u32,
    pub lines: Vec<DiffLine>,
}

#[derive(Serialize)]
pub struct DiffLine {
    pub kind: LineKind,      // Context, Addition, Deletion
    pub content: String,
    pub old_line_no: Option<u32>,
    pub new_line_no: Option<u32>,
}

#[derive(Serialize)]
pub struct ChangeStats {
    pub files_changed: usize,
    pub insertions: usize,
    pub deletions: usize,
}
```

### API Endpoint

```rust
// WebSocket message handler
"git_changes" => {
    let session_id = msg.session_id;
    let working_dir = get_session_working_dir(session_id)?;
    let changes = git_changes::get_unstaged_changes(&working_dir)?;
    Ok(ChangesResponse { working_dir, ...changes })
}
```

### Implementation Options

1. **git2 crate** (libgit2 bindings)
   - Pure Rust, no shell
   - More complex API
   - Full control over diff options

2. **Shell out to git**
   - Simpler implementation
   - Parse `git diff --no-color` output
   - Relies on git being installed

**Recommendation**: Start with shelling out to `git diff` - simpler to implement, and git is already required for the session to be meaningful. Can migrate to git2 later if needed.

## Frontend (React/TypeScript)

### Location
`web/ui/src/components/ChangesView/`

### Components

```
ChangesView/
├── index.tsx           # Main container, data fetching
├── FileList.tsx        # List of changed files
├── FileItem.tsx        # Single file row (tap to expand)
├── DiffViewer.tsx      # Unified diff display
├── HunkView.tsx        # Single hunk with line numbers
└── styles.css          # Mobile-optimized styles
```

### Key UI Elements

```
┌─────────────────────────────────┐
│ Changes           ↻  [Refresh] │
│ ~/projects/balloons             │
├─────────────────────────────────┤
│ 3 files · +42 -17               │
├─────────────────────────────────┤
│ ▶ M  src/cache.py      +12 -3  │
│ ▼ M  src/utils.py       +8 -2  │
│ ┌─────────────────────────────┐ │
│ │ @@ -15,6 +15,8 @@           │ │
│ │  15   def helper():         │ │
│ │  16       pass               │ │
│ │     + new_line_1             │ │
│ │     + new_line_2             │ │
│ │  17   return result          │ │
│ └─────────────────────────────┘ │
│ ▶ A  new_file.txt      +22 -0  │
└─────────────────────────────────┘
```

### Mobile Considerations

- **Large tap targets**: File rows at least 48px tall
- **Horizontal scroll for long lines**: Diff content scrolls independently
- **Syntax highlighting**: Optional, keep lightweight (highlight.js already available)
- **Dark mode**: Match existing Balloons theme
- **Pull to refresh**: Native feel on mobile

### TypeScript Types

```typescript
interface ChangesResponse {
  working_dir: string;
  files: FileDiff[];
  stats: ChangeStats;
}

interface FileDiff {
  path: string;
  status: 'modified' | 'added' | 'deleted' | 'renamed';
  hunks: Hunk[];
  stats: { additions: number; deletions: number };
}

interface Hunk {
  header: string;
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  lines: DiffLine[];
}

interface DiffLine {
  kind: 'context' | 'addition' | 'deletion';
  content: string;
  old_line_no?: number;
  new_line_no?: number;
}
```

## Implementation Phases

### Phase 1: Backend Foundation
1. Add `git_changes` module to `balloons-browser`
2. Implement `get_unstaged_changes()` using git CLI
3. Parse unified diff output into structured data
4. Add WebSocket message handler
5. Unit tests with sample diff outputs

### Phase 2: Basic Frontend
1. Create `ChangesView` component structure
2. Fetch changes on mount/refresh
3. Display file list with stats
4. Basic expand/collapse for files
5. Render diff lines with +/- indicators

### Phase 3: Polish
1. Syntax highlighting for diff content
2. Pull-to-refresh gesture
3. Line numbers in gutter
4. "No changes" empty state
5. Error handling (not a git repo, etc.)

## Future Enhancements (Post-MVP)

### Near-term
- **Staged changes**: Show staged vs unstaged sections
- **File filtering**: Search/filter changed files (helpful with large agent-generated changes)
- **Binary file handling**: Show "Binary file changed"
- **Jump to file in conversation**: Link back to where Claude discussed this file

### Longer-term (if mobile editing becomes viable)
- **Stage/unstage**: Swipe gestures or buttons
- **Hunk-level staging**: Stage individual hunks
- **Commit flow**: Inline commit message + confirm (with Claude's suggested message?)
- **Request changes**: "Claude, revert this file" or "Claude, rename this function" from mobile

### Ambitious
- **Session attribution**: Track which session made which changes, show per-session diffs
- **Change timeline**: See changes over time as agent worked
- **Submodule support**: Handle submodule changes gracefully

---

## Long-term Vision: Collaborative Code Review Interface

The Changes view is the seed for something larger: a **full-service code browser with git integration** that enables granular, annotated collaboration between developer and AI agent.

### The Core Idea

Rather than just viewing diffs, this evolves into a space where you can:

1. **Browse the full codebase** - not just changes, but any file
2. **Annotate code regions** - highlight areas with comments, questions, or directives
3. **Guide agent direction** - mark sections as "discuss this approach," "consider refactoring," "don't touch this"
4. **Review incrementally** - approve/reject changes at the hunk or line level
5. **Track intent** - see not just *what* changed but *why* (linked to conversation context)

### Conceptual UI

```
┌─────────────────────────────────────────────────────────────┐
│  Code Browser                              [Tree] [Changes] │
├─────────────────────────────────────────────────────────────┤
│  src/auth/                                                  │
│  ├── login.py           M  +45 -12  [2 comments]           │
│  ├── oauth.py           A  +120     [needs review]         │
│  └── session.py         M  +8 -3    ✓ approved             │
├─────────────────────────────────────────────────────────────┤
│  src/auth/login.py                           [Full] [Diff] │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │  45   def validate_token(token: str):                   │ │
│ │  46 +     if not token:                     💬 ← [tap]  │ │
│ │  47 +         raise AuthError("Empty token")            │ │
│ │  48       try:                                          │ │
│ │  49 +         decoded = jwt.decode(token, SECRET)       │ │
│ │       ┌────────────────────────────────────┐            │ │
│ │       │ 💬 You: "Should this use the new   │            │ │
│ │       │ verify_jwt() helper instead?"      │            │ │
│ │       │                                    │            │ │
│ │       │ [Ask Claude] [Mark Resolved]       │            │ │
│ │       └────────────────────────────────────┘            │ │
│ │  50           return decoded["user_id"]                 │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Key Capabilities

#### 1. Code Annotations
- **Inline comments** on any line or region
- **Annotation types**: question, suggestion, directive, approval, concern
- Annotations persist and sync across sessions
- Agent can see annotations and respond

#### 2. Review Workflow
- **Per-hunk approval**: ✓ approve, ✗ reject, 💬 discuss
- **Batch operations**: "approve all in this file"
- **Review status**: track what's been reviewed vs pending
- Changes can be filtered by review status

#### 3. Code Navigation
- **File tree browser** alongside changes view
- **Jump to definition** (if LSP data available)
- **Search across codebase**
- **Git history** for context on pre-existing code

#### 4. Agent Collaboration
- **"Ask Claude about this"** on any selection
- **Directive annotations**: "refactor this," "add tests for this," "explain this"
- **Approach markers**: tag code with intended patterns/goals
- Agent sees annotations as context for future work

#### 5. Intent Tracking
- Link changes to conversation turns where they were discussed
- Show *why* a change was made (agent's reasoning)
- Surface relevant discussion when viewing code

### Data Model Extensions

```typescript
interface CodeAnnotation {
  id: string;
  file_path: string;
  start_line: number;
  end_line: number;
  type: 'question' | 'suggestion' | 'directive' | 'approval' | 'concern';
  content: string;
  author: 'user' | 'agent';
  created_at: Date;
  resolved: boolean;
  linked_turn?: string;  // conversation turn that prompted this
}

interface ReviewStatus {
  file_path: string;
  hunk_index: number;
  status: 'pending' | 'approved' | 'rejected' | 'discussing';
  reviewer_notes?: string;
}

interface ChangeIntent {
  file_path: string;
  line_range: [number, number];
  intent: string;           // "refactoring for readability"
  linked_turns: string[];   // conversation context
  session_id: string;
}
```

### Why This Matters

Traditional code review tools assume:
- Two humans with different context
- Pull request as atomic unit
- Asynchronous, sequential feedback

AI-assisted development is different:
- Agent and human building shared understanding in real-time
- Changes are incremental and explorable
- Feedback should guide ongoing work, not just accept/reject

This view becomes the **developer's cockpit** for steering AI-assisted development—seeing what changed, understanding why, and directing where to go next.

### Phased Approach

| Phase | Focus | Key Features |
|-------|-------|--------------|
| MVP | View changes | Read-only diff view, file list |
| v1.1 | Navigate | File tree, full file view, search |
| v1.2 | Annotate | Inline comments, basic annotation types |
| v1.3 | Review | Hunk approval, review status |
| v2.0 | Collaborate | Agent sees annotations, directive support |
| v2.x | Intent | Change-to-conversation linking, reasoning display |

## Open Questions

1. **Tab vs command?** Should this be a persistent tab (like Slides) or a `:changes` command that opens a view? Given the use case ("check what Claude did"), a persistent tab feels right.

2. **Auto-refresh?** Since you're reviewing agent work that's likely still running, some form of refresh is useful. Options:
   - Manual refresh button (simplest)
   - Poll every N seconds when tab is active
   - Push updates when agent modifies files (more complex)

3. **Large diffs?** Agent-generated changes can be substantial. Ideas:
   - Collapse files by default, expand on tap
   - Show file-level summary first (+/- counts)
   - Lazy-load diff content per file
   - "This file has 500+ lines changed" warning with expand option

4. **Attributing changes to sessions?** Since multiple sessions could touch the same repo, should we try to show which session made which changes? Probably out of scope for MVP—just show the combined unstaged diff.

## Dependencies

### Rust
- `git2` (optional, if moving away from CLI)
- `serde` / `serde_json` (already used)

### TypeScript
- `highlight.js` or `prism` (already in project for code highlighting)
- No new dependencies expected

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Large repos with many changes | Paginate file list, lazy-load diffs |
| Binary files in diff | Detect and show placeholder |
| No git installed | Clear error message |
| Not a git repo | Clear error message |
| Very long lines | Horizontal scroll with line wrapping option |

---

*Last updated: 2025-02-19*
