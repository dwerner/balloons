# Plan: Code Tab with Inline Review

## Goal
Replace the "Changes" tab with a "Code" tab that provides a unified code review interface. Users can view unstaged git changes, pull in arbitrary files, and compose multi-file reviews with inline comments. Submitting a review creates a single structured turn in the chat that provides rich context to the assistant.

## Core Concept

The Code Tab serves two purposes:
1. **Diff viewer**: Show unstaged working directory changes (git diff)
2. **Code reference tool**: Pull in any file to comment on and reference

A "review" is a modal workflow where the user accumulates comments across files, then submits them as a single structured message. This enables rich, contextual communication about code without copy-pasting snippets into chat.

## User Experience

### Default State (No Review Active)
- File list sidebar shows files with unstaged changes
- Clicking a file shows its diff via react-diff-view
- "Start Review" button is visible
- Can browse diffs but cannot add comments

### Review Mode
- Visual indicator: banner showing "Review in progress (N comments)"
- Tab title: "Code (reviewing)"
- Comments can be added to:
  - Lines in diffs (changed files)
  - Lines in file references (any file from browser)
- "Submit Review" button becomes prominent
- "Cancel Review" discards accumulated comments

### Adding Comments
**On diff lines:**
- Click a line → inline comment input appears (react-diff-view widget)
- Click-drag or shift-click → select line range, then comment
- Comment captures hunk context automatically

**On file references:**
- From file browser: "Add to Review" action on any file
- Opens file in Code tab with line selection enabled
- Same comment UX: click line or select range
- Context = selected lines (not a diff, just code snapshot)

### Submitting Review
- Serializes all comments with their context snapshots
- Creates a `user-code-review` message type in chat
- Clears review state
- Clears localStorage backup

## Data Model

```typescript
interface CodeReviewComment {
  id: string;
  file_path: string;
  line_start: number;
  line_end?: number;  // for multi-line selections
  comment: string;    // freeform text

  // Context snapshot (what the assistant sees)
  context_type: 'diff' | 'file_reference';
  context_lines: string[];  // the actual code lines

  // For diffs only
  diff_hunk?: string;       // the full hunk containing this change
  change_type?: 'add' | 'delete' | 'modify';
}

interface CodeReview {
  id: string;
  comments: CodeReviewComment[];
  created_at: string;
}

interface ReviewState {
  active: boolean;
  review: CodeReview | null;
}
```

## Message Format: user-code-review

When a review is submitted, it becomes a special message type that renders distinctively in chat.

### Visual Rendering (User Sees)
```
┌─────────────────────────────────────────────────────┐
│ Code Review (3 comments)                            │
├─────────────────────────────────────────────────────┤
│ src/cache.py:42-45 (modified)                       │
│ ┌─────────────────────────────────────────────────┐ │
│ │- old_value = cache.get(key)                     │ │
│ │+ new_value = cache.get(key, default=None)       │ │
│ └─────────────────────────────────────────────────┘ │
│ "This default should probably come from config"     │
├─────────────────────────────────────────────────────┤
│ src/utils.py:120-125 (reference)                    │
│ ┌─────────────────────────────────────────────────┐ │
│ │ def validate_input(data):                       │ │
│ │     if not isinstance(data, dict):             │ │
│ │         raise ValueError("Expected dict")       │ │
│ └─────────────────────────────────────────────────┘ │
│ "Use this same pattern in the new endpoint"         │
├─────────────────────────────────────────────────────┤
│ src/api.py:88 (added)                               │
│ ┌─────────────────────────────────────────────────┐ │
│ │+ @cache_result(ttl=300)                         │ │
│ └─────────────────────────────────────────────────┘ │
│ "Nice!"                                             │
└─────────────────────────────────────────────────────┘
```

### What the Assistant Receives
The assistant sees structured data enabling it to:
- Navigate to exact file + line locations
- Understand whether it's a diff (has old/new) or reference (just context)
- Read the user's freeform comment to understand intent
- Distinguish actionable requests from contextual observations

Comment semantics are determined by the text itself:
- "Fix this" / "Change X to Y" → actionable
- "Nice!" / "More like this" → contextual/positive feedback
- "Look at this pattern" → reference for future use

## Technical Implementation

### Dependencies
- **react-diff-view**: Diff rendering with widget support for inline comments
- **Existing git bindings**: Python+Rust integration for `git diff` output

### Backend API

```
GET /api/git/diff
  Returns: List of files with unstaged changes, each with hunks in unified diff format

GET /api/git/file?path=<path>
  Returns: Full file content (for file references)
```

### Component Structure

```
src/components/
  CodeTab/
    index.tsx              # Main container, manages review state
    DiffView.tsx           # react-diff-view wrapper
    FileList.tsx           # Changed files sidebar
    FileReference.tsx      # Non-diff file viewer with selection
    ReviewBanner.tsx       # "Review in progress" indicator
    CommentWidget.tsx      # Inline comment input (react-diff-view widget)
    CommentThread.tsx      # Displays existing comment on a line

  ChatCards/
    UserCodeReviewCard.tsx # Renders submitted review in chat
```

### State Management

```typescript
// In CodeTab or context
const [reviewState, setReviewState] = useState<ReviewState>({
  active: false,
  review: null
});

// localStorage backup for crash recovery
useEffect(() => {
  if (reviewState.active && reviewState.review) {
    localStorage.setItem('draft-review', JSON.stringify(reviewState.review));
  }
}, [reviewState]);

// On mount, check for recovered draft
useEffect(() => {
  const draft = localStorage.getItem('draft-review');
  if (draft) {
    // Prompt user: "Recover draft review?"
  }
}, []);
```

### Data Flow

```
┌─────────────────┐     ┌──────────────────┐
│ Git (Rust/Py)   │────▶│ /api/git/diff    │
│ working dir     │     │ returns hunks    │
└─────────────────┘     └────────┬─────────┘
                                 │
                                 ▼
┌─────────────────┐     ┌──────────────────┐
│ File Browser    │────▶│ CodeTab          │
│ "Add to Review" │     │ - DiffView       │
└─────────────────┘     │ - FileReference  │
                        │ - ReviewState    │
                        └────────┬─────────┘
                                 │ Submit
                                 ▼
                        ┌──────────────────┐
                        │ Chat Turn        │
                        │ user-code-review │
                        └──────────────────┘
```

## react-diff-view Integration

### Widget System for Comments
react-diff-view provides a widget architecture for attaching React elements to diff lines:

```tsx
import { Diff, getChangeKey } from 'react-diff-view';

// Build widgets from review comments
const widgets = useMemo(() => {
  if (!reviewState.active) return {};

  return reviewState.review.comments.reduce((acc, comment) => {
    const key = getChangeKey(comment.change);
    acc[key] = {
      change: comment.change,
      element: <CommentThread comment={comment} />
    };
    return acc;
  }, {});
}, [reviewState]);

<Diff
  hunks={hunks}
  widgets={widgets}
  // renderGutter for "add comment" button on hover
/>
```

### Change Key Format
- Insert changes: `'I' + lineNumber`
- Delete changes: `'D' + lineNumber`
- Normal changes: `'N' + oldLineNumber`

Use `getChangeKey(change)` helper to compute keys.

## File Browser Integration

Add "Add to Review" context menu action:
1. User right-clicks file in browser
2. Selects "Add to Review"
3. File opens in Code tab (non-diff view)
4. User can select lines and add comments
5. File reference is added to active review

If no review is active, "Add to Review" starts one automatically.

## Future Enhancements

- **File watching**: Live updates when working directory changes
- **Comment types**: Labels like "suggestion", "question", "nitpick"
- **Threads**: Reply chains on comments
- **Resolve/unresolve**: Track which comments have been addressed
- **Git history**: View diffs against specific commits (not just unstaged)
- **Staging integration**: Stage/unstage files from the Code tab

## Files to Create/Modify

### New Files
- `web/ui/src/components/CodeTab/index.tsx`
- `web/ui/src/components/CodeTab/DiffView.tsx`
- `web/ui/src/components/CodeTab/FileList.tsx`
- `web/ui/src/components/CodeTab/FileReference.tsx`
- `web/ui/src/components/CodeTab/ReviewBanner.tsx`
- `web/ui/src/components/CodeTab/CommentWidget.tsx`
- `web/ui/src/components/CodeTab/CommentThread.tsx`
- `web/ui/src/components/ChatCards/UserCodeReviewCard.tsx`

### Modifications
- `web/ui/src/App.tsx` - Add Code tab, wire up routing
- `web/ui/src/components/FileBrowser.tsx` - Add "Add to Review" action
- `balloons/server.py` - Add `/api/git/diff` endpoint
- `balloons/git_utils.py` - Wrap git bindings for diff output
- Message type handling for `user-code-review` in chat

### Dependencies to Add
- `react-diff-view` npm package
- `diff` npm package (peer dependency)
