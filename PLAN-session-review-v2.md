# Session Review & Summary Feature

## Overview

Add a right-click context menu option on sessions in the tree view that triggers an LLM review of the session. The review generates a structured summary that is stored as a turn in the session history, creating a traceable point-in-time snapshot.

## User Flow

1. User right-clicks a session in the tree view
2. Context menu appears with "Review & Summarize" option
3. **Unified review dialog** opens with:
   - **Left sidebar**: Backend selector dropdown + "Generate" button + list of past reviews
   - **Main area**: Empty state prompting to generate or select past review
4. User selects backend and clicks "Generate"
5. LLM analyzes session → generates structured review → displays in main area:
   - **Title field**: Editable session title (pre-filled with LLM suggestion)
   - **Summary area**: Markdown content with **Preview/Edit toggle**
     - Preview mode: Rendered markdown (default)
     - Edit mode: Syntax-highlighted markdown editor
   - **Metadata**: Which backend, turn count at review time
6. User can:
   - Edit the title
   - Switch to Edit mode and modify the markdown
   - Click a past review in sidebar to view/compare
   - Re-generate with a different backend
   - Approve & Save or Cancel
7. On approve:
   - Summary is saved as a turn in the session (with edited markdown)
   - Session title is updated if changed
   - The turn is visible in conversation, showing what the session contained at that point

## Why Store as a Turn?

Storing the review as a turn (rather than just metadata) provides:

1. **Traceability**: If more work happens after the review, there's a clear marker showing what was completed up to that point
2. **Context for LLM**: Future conversations can reference the summary
3. **Audit trail**: Multiple reviews over time show session evolution
4. **Fork-safe**: Reviews propagate correctly through fork/merge operations

## Data Model

### SessionSummaryBlock

New content block type for storing session reviews:

```python
@ws_type
@dataclass
class SessionSummaryBlock:
    """A point-in-time summary of the session state.

    Created when user reviews a session. Stored as a turn to preserve
    a traceable record of what the session contained at that moment.
    """
    type: str = "session_summary"
    summary_id: str = ""  # UUID for this summary

    # LLM-generated content (editable by user)
    proposed_title: str = ""  # Suggested session title
    markdown_content: str = ""  # Full summary as editable markdown (primary storage)

    # Structured fields (parsed from markdown, for display/search)
    files_modified: list[str] = field(default_factory=list)  # e.g., ["src/foo.py (created)"]
    decisions_made: list[str] = field(default_factory=list)  # Key choices
    work_done: str = ""  # Summary paragraph
    next_steps: list[str] = field(default_factory=list)  # Deferred/incomplete items
    questions_raised: list[str] = field(default_factory=list)  # Open questions

    # Metadata
    turn_count_at_review: int = 0  # Turns when reviewed (for context)
    reviewed_at: str = ""  # ISO timestamp
    reviewed_by_backend: str = ""  # Which backend generated this review (e.g., "claude-sonnet", "gpt-4")

    # Approval state
    status: str = "pending"  # "pending", "approved", "rejected"
    approved_title: str = ""  # Final title (may differ from proposed)
```

### Add to ContentBlock Union

```python
ContentBlock = Union[..., SessionSummaryBlock]
```

## Review Prompt

Located in `prompts/session-review.md`:

```markdown
Analyze this conversation and provide a structured session review.

Respond in EXACTLY this format (keep field names exactly as shown):

PROPOSED_TITLE:
A concise, descriptive title for this session (max 50 chars)

FILES_MODIFIED:
- file1.py (created)
- file2.py (modified)
- file3.py (deleted)

DECISIONS_MADE:
- Decision 1: Why this choice was made
- Decision 2: Why this choice was made

WORK_DONE:
1-3 sentences describing what was accomplished in this session.

NEXT_STEPS:
- Unfinished item 1
- Deferred task 2

QUESTIONS_RAISED:
- Open question that wasn't resolved
- Another uncertainty

Guidelines:
- If no files were modified, write "None" for FILES_MODIFIED
- If no decisions, write "None" for DECISIONS_MADE
- PROPOSED_TITLE should be specific (e.g., "Implement Redis caching" not "Work on caching")
- WORK_DONE should focus on outcomes, not process
- NEXT_STEPS captures anything explicitly deferred or left incomplete
- QUESTIONS_RAISED captures uncertainties mentioned but not resolved

Conversation:
{conversation}

Session review:
```

## UI Components

### 1. Session Context Menu

Enhance `SessionTreeView.tsx` to add a context menu at the session level (not just exchange level):

```tsx
interface SessionContextMenuProps {
  position: { x: number; y: number };
  session: SessionInfo;
  onReview: () => void;
  onRename: () => void;
  onArchive: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function SessionContextMenu({ ... }: SessionContextMenuProps) {
  return createPortal(
    <div className="session-context-menu" style={{ left: position.x, top: position.y }}>
      <button onClick={onReview}>
        <ReviewIcon /> Review & Summarize
      </button>
      <button onClick={onRename}>
        <EditIcon /> Rename
      </button>
      <div className="divider" />
      <button onClick={onArchive}>
        <ArchiveIcon /> Archive
      </button>
      <button className="danger" onClick={onDelete}>
        <TrashIcon /> Delete
      </button>
    </div>,
    document.body
  );
}
```

### 2. SessionReviewModal (Unified Dialog)

Single dialog for all session review operations:
- Backend selection + generation
- View/edit review content with markdown toggle
- Browse past reviews for this session

**Layout:**
```
┌─────────────────────────────────────────────────────────────────┐
│  Session Review                                            [X]  │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────────┐  ┌─────────────────────────────────────────┐   │
│ │ Generate     │  │ Session Title: [___________________]   │   │
│ │ ┌──────────┐ │  │                                         │   │
│ │ │ Backend ▼│ │  │ Summary            [Preview] [Edit]     │   │
│ │ └──────────┘ │  │ ┌─────────────────────────────────────┐ │   │
│ │ [Generate]   │  │ │ ## Work Done                        │ │   │
│ │              │  │ │ Implemented session review feature  │ │   │
│ │ ────────────  │  │ │ with backend selection...           │ │   │
│ │              │  │ │                                     │ │   │
│ │ Past Reviews │  │ │ ## Files Modified                   │ │   │
│ │ ○ Feb 24     │  │ │ - models.py (modified)              │ │   │
│ │   claude-3   │  │ │ - core/summarizer.py (modified)     │ │   │
│ │ ● Feb 23 ✓   │  │ │                                     │ │   │
│ │   gpt-4      │  │ │ ## Decisions Made                   │ │   │
│ │              │  │ │ - Store reviews as turns for        │ │   │
│ │              │  │ │   traceability                      │ │   │
│ └──────────────┘  │ └─────────────────────────────────────┘ │   │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│                              [Cancel]  [Approve & Save]          │
└─────────────────────────────────────────────────────────────────┘
```

New component `components/SessionReviewModal/SessionReviewModal.tsx`:

```tsx
interface SessionReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  sessionId: string;
  client: SessionManagerServiceClient;
  availableBackends: BackendInfo[];
  defaultBackend?: string;
  existingReviews: SessionSummaryBlock[];  // Past reviews for this session
  onApproved?: (summary: SessionSummaryBlock) => void;
}

function SessionReviewModal({
  isOpen, onClose, sessionId, client,
  availableBackends, defaultBackend, existingReviews, onApproved
}: SessionReviewModalProps) {
  // State
  const [selectedBackend, setSelectedBackend] = useState(defaultBackend || '');
  const [isGenerating, setIsGenerating] = useState(false);
  const [review, setReview] = useState<SessionSummaryBlock | null>(null);
  const [editedTitle, setEditedTitle] = useState('');
  const [editedMarkdown, setEditedMarkdown] = useState('');  // Full summary as markdown
  const [isEditMode, setIsEditMode] = useState(false);  // Preview vs Edit toggle
  const [viewingHistoryIndex, setViewingHistoryIndex] = useState<number | null>(null);

  // Reset when modal opens
  useEffect(() => {
    if (isOpen) {
      setSelectedBackend(defaultBackend || availableBackends[0]?.name || '');
      setReview(null);
      setEditedTitle('');
      setEditedMarkdown('');
      setIsGenerating(false);
      setIsEditMode(false);
      setViewingHistoryIndex(null);
    }
  }, [isOpen, defaultBackend, availableBackends]);

  // Generate new review with selected backend
  const handleGenerate = async () => {
    setIsGenerating(true);
    setViewingHistoryIndex(null);
    try {
      const result = await client.reviewSession(sessionId, selectedBackend);
      setReview(result);
      setEditedTitle(result.proposed_title);
      setEditedMarkdown(formatReviewAsMarkdown(result));
    } finally {
      setIsGenerating(false);
    }
  };

  // Load a past review from history
  const handleSelectHistory = (index: number) => {
    const pastReview = existingReviews[index];
    setViewingHistoryIndex(index);
    setReview(pastReview);
    setEditedTitle(pastReview.approved_title || pastReview.proposed_title);
    setEditedMarkdown(formatReviewAsMarkdown(pastReview));
    setIsEditMode(false);  // Start in preview mode for history
  };

  // Approve and save
  const handleApprove = async () => {
    if (!review) return;
    // Parse markdown back to structured data if edited
    const finalReview = isEditMode
      ? parseMarkdownToReview(editedMarkdown, review)
      : review;
    await client.approveSessionReview(sessionId, finalReview.summary_id, editedTitle, editedMarkdown);
    onApproved?.(finalReview);
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Session Review" size="large">
      <div className="session-review-modal">
        {/* Sidebar: Backend selection + History */}
        <aside className="session-review-modal__sidebar">
          {/* Backend selector */}
          <div className="sidebar-section">
            <label className="sidebar-label">Generate with</label>
            <select
              value={selectedBackend}
              onChange={e => setSelectedBackend(e.target.value)}
              disabled={isGenerating}
              className="backend-select"
            >
              {availableBackends.map(b => (
                <option key={b.name} value={b.name}>{b.displayName}</option>
              ))}
            </select>
            <button
              onClick={handleGenerate}
              disabled={isGenerating || !selectedBackend}
              className="btn btn-primary generate-btn"
            >
              {isGenerating ? 'Generating...' : 'Generate'}
            </button>
          </div>

          {/* Past reviews */}
          {existingReviews.length > 0 && (
            <div className="sidebar-section">
              <label className="sidebar-label">Past Reviews</label>
              <ul className="history-list">
                {existingReviews.map((r, i) => (
                  <li
                    key={r.summary_id}
                    className={`history-item ${viewingHistoryIndex === i ? 'active' : ''}`}
                    onClick={() => handleSelectHistory(i)}
                  >
                    <span className="history-date">{formatDate(r.reviewed_at)}</span>
                    <span className="history-backend">{r.reviewed_by_backend}</span>
                    {r.status === 'approved' && <span className="history-badge">✓</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>

        {/* Main content */}
        <main className="session-review-modal__main">
          {isGenerating ? (
            <div className="loading-state">
              <LoadingSpinner />
              <p>Generating review with {selectedBackend}...</p>
            </div>
          ) : review ? (
            <div className="review-content">
              {/* Title field */}
              <div className="title-field">
                <label>Session Title</label>
                <input
                  value={editedTitle}
                  onChange={e => setEditedTitle(e.target.value)}
                  className="title-input"
                  placeholder="Enter session title..."
                />
              </div>

              {/* Summary with Preview/Edit toggle */}
              <div className="summary-field">
                <div className="summary-header">
                  <label>Summary</label>
                  <div className="mode-toggle">
                    <button
                      className={`toggle-btn ${!isEditMode ? 'active' : ''}`}
                      onClick={() => setIsEditMode(false)}
                    >
                      Preview
                    </button>
                    <button
                      className={`toggle-btn ${isEditMode ? 'active' : ''}`}
                      onClick={() => setIsEditMode(true)}
                    >
                      Edit
                    </button>
                  </div>
                </div>

                <div className="summary-body">
                  {isEditMode ? (
                    <MarkdownEditor
                      value={editedMarkdown}
                      onChange={setEditedMarkdown}
                      className="summary-editor"
                    />
                  ) : (
                    <div className="summary-preview">
                      <MarkdownRenderer content={editedMarkdown} />
                    </div>
                  )}
                </div>
              </div>

              {/* Metadata footer */}
              <div className="review-meta">
                <span>Generated by {review.reviewed_by_backend}</span>
                <span>•</span>
                <span>At turn {review.turn_count_at_review}</span>
                {viewingHistoryIndex !== null && (
                  <>
                    <span>•</span>
                    <span className="viewing-past">Viewing past review</span>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="empty-state">
              <p>Select a backend and click <strong>Generate</strong> to review this session.</p>
              {existingReviews.length > 0 && (
                <p className="hint">Or select a past review from the sidebar.</p>
              )}
            </div>
          )}
        </main>
      </div>

      <ModalFooter>
        <button onClick={onClose} className="btn">Cancel</button>
        <button
          onClick={handleApprove}
          className="btn btn-primary"
          disabled={!review || !editedTitle.trim()}
        >
          Approve & Save
        </button>
      </ModalFooter>
    </Modal>
  );
}

// Convert structured review to markdown for editing
function formatReviewAsMarkdown(review: SessionSummaryBlock): string {
  const sections: string[] = [];

  if (review.work_done) {
    sections.push(`## Summary\n\n${review.work_done}`);
  }

  if (review.files_modified.length > 0) {
    const items = review.files_modified.map(f => `- ${f}`).join('\n');
    sections.push(`## Files Modified\n\n${items}`);
  }

  if (review.decisions_made.length > 0) {
    const items = review.decisions_made.map(d => `- ${d}`).join('\n');
    sections.push(`## Decisions Made\n\n${items}`);
  }

  if (review.next_steps.length > 0) {
    const items = review.next_steps.map(n => `- ${n}`).join('\n');
    sections.push(`## Next Steps\n\n${items}`);
  }

  if (review.questions_raised.length > 0) {
    const items = review.questions_raised.map(q => `- ${q}`).join('\n');
    sections.push(`## Open Questions\n\n${items}`);
  }

  return sections.join('\n\n');
}

// Parse edited markdown back to structured fields
function parseMarkdownToReview(
  markdown: string,
  original: SessionSummaryBlock
): SessionSummaryBlock {
  // Parse markdown sections back to structured data
  // This is the inverse of formatReviewAsMarkdown
  const result = { ...original };

  // Simple section parser
  const sections = markdown.split(/^## /m).filter(Boolean);
  for (const section of sections) {
    const [header, ...content] = section.split('\n');
    const body = content.join('\n').trim();

    if (header?.toLowerCase().includes('summary')) {
      result.work_done = body;
    } else if (header?.toLowerCase().includes('files')) {
      result.files_modified = parseListItems(body);
    } else if (header?.toLowerCase().includes('decisions')) {
      result.decisions_made = parseListItems(body);
    } else if (header?.toLowerCase().includes('next')) {
      result.next_steps = parseListItems(body);
    } else if (header?.toLowerCase().includes('questions')) {
      result.questions_raised = parseListItems(body);
    }
  }

  return result;
}

function parseListItems(text: string): string[] {
  return text
    .split('\n')
    .map(line => line.replace(/^[-*]\s*/, '').trim())
    .filter(Boolean);
}
```

### 3. MarkdownEditor Component

Syntax-highlighted markdown editor for the summary field:

```tsx
interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  className?: string;
}

function MarkdownEditor({ value, onChange, className }: MarkdownEditorProps) {
  // Options for implementation:
  // 1. CodeMirror 6 with markdown language support
  // 2. Monaco Editor (heavier but feature-rich)
  // 3. Simple textarea with syntax highlighting overlay
  // 4. @uiw/react-md-editor (all-in-one)

  return (
    <div className={`markdown-editor ${className || ''}`}>
      <textarea
        value={value}
        onChange={e => onChange(e.target.value)}
        className="markdown-textarea"
        spellCheck={false}
        placeholder="# Summary\n\nDescribe what was accomplished..."
      />
    </div>
  );
}
```

### 4. MarkdownRenderer Component

For the preview mode:

```tsx
interface MarkdownRendererProps {
  content: string;
  className?: string;
}

function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  // Use react-markdown or similar
  return (
    <div className={`markdown-preview ${className || ''}`}>
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}
```

## Backend Implementation

### 1. Summarizer Extension

Add to `core/summarizer.py`:

```python
def build_session_review_prompt(self, session: Session) -> str:
    """Build the prompt for session review generation."""
    # Similar to build_archive_summary_prompt but with session-review.md template
    ...

async def generate_session_review(self, session: Session) -> SessionSummaryBlock:
    """Generate a structured review of a session."""
    prompt = self.build_session_review_prompt(session)
    stream_id = self._register_stream(StreamType.SESSION_REVIEW, f"Reviewing: {session.title}")

    response_parts = []
    async for event in self._runner.stream_response([], prompt, disable_tools=True):
        if isinstance(event, TextDelta):
            response_parts.append(event.text)

    response = "".join(response_parts)
    return self._parse_session_review(response, session)

def _parse_session_review(self, response: str, session: Session) -> SessionSummaryBlock:
    """Parse LLM response into SessionSummaryBlock."""
    # Similar to _parse_archive_summary but for review format
    ...
```

### 2. Session Manager Service

Add RPCs in `service/session_manager_service.py`:

```python
@rpc
async def review_session(self, session_id: str, backend_name: str) -> SessionSummaryBlock:
    """Generate a review of the session using the specified backend.

    Args:
        session_id: The session to review
        backend_name: Which backend to use for generating the review
                     (e.g., "claude-sonnet", "gpt-4", "gemini-pro")
    """
    session = await self._session_manager.get_session(session_id)
    if not session:
        raise ValueError(f"Session not found: {session_id}")

    # Get or create a summarizer with the specified backend
    summarizer = await self._get_summarizer_for_backend(backend_name)

    # Generate review using summarizer
    review = await summarizer.generate_session_review(session)
    review.reviewed_by_backend = backend_name

    # Add as pending turn to session
    turn = Turn(
        role="system",
        content_block=review,
    )
    session.turns.append(turn)
    await self._session_manager.save_session(session)

    return review

async def _get_summarizer_for_backend(self, backend_name: str) -> Summarizer:
    """Get a Summarizer instance configured for the specified backend.

    This allows using different models for review tasks:
    - Cheaper/faster models for routine reviews
    - More capable models for complex sessions
    """
    # Look up backend configuration
    backend_config = self._config.get_backend(backend_name)
    if not backend_config:
        raise ValueError(f"Unknown backend: {backend_name}")

    # Create a runner for this backend
    runner = await self._create_runner_for_backend(backend_config)

    return Summarizer(runner, backend_name=backend_name)

@rpc
async def approve_session_review(
    self,
    session_id: str,
    summary_id: str,
    approved_title: str
) -> bool:
    """Approve a session review and update session title."""
    session = await self._session_manager.get_session(session_id)

    # Find the pending review turn
    for turn in session.turns:
        if (isinstance(turn.content_block, SessionSummaryBlock)
            and turn.content_block.summary_id == summary_id):
            turn.content_block.status = "approved"
            turn.content_block.approved_title = approved_title
            break

    # Update session title
    session.title = approved_title
    await self._session_manager.save_session(session)

    return True
```

### 3. StreamType Extension

Add to `core/stream_state.py`:

```python
class StreamType(Enum):
    ...
    SESSION_REVIEW = "session_review"
```

## Display in Conversation

The `SessionSummaryBlock` should render nicely in the conversation view:

```tsx
function SessionSummaryTurn({ block }: { block: SessionSummaryBlock }) {
  const isApproved = block.status === "approved";

  return (
    <div className={`session-summary-turn ${isApproved ? 'approved' : 'pending'}`}>
      <div className="session-summary-header">
        <span className="icon">📋</span>
        <span className="title">Session Review</span>
        {isApproved && <span className="badge">Approved</span>}
        <span className="timestamp">{formatDate(block.reviewed_at)}</span>
        <span className="backend">{block.reviewed_by_backend}</span>
      </div>

      <div className="session-summary-content">
        <div className="field">
          <label>Title:</label>
          <span>{isApproved ? block.approved_title : block.proposed_title}</span>
        </div>

        {block.work_done && (
          <div className="field">
            <label>Summary:</label>
            <p>{block.work_done}</p>
          </div>
        )}

        {block.files_modified.length > 0 && (
          <div className="field">
            <label>Files:</label>
            <ul>{block.files_modified.map(f => <li key={f}>{f}</li>)}</ul>
          </div>
        )}

        {/* ... other fields ... */}
      </div>
    </div>
  );
}
```

## Implementation Order

1. **Models** (`models.py`)
   - Add `SessionSummaryBlock` dataclass
   - Add to `ContentBlock` union

2. **Prompt** (`prompts/session-review.md`)
   - Create the review prompt template

3. **Summarizer** (`core/summarizer.py`)
   - Add `build_session_review_prompt()`
   - Add `generate_session_review()`
   - Add `_parse_session_review()`

4. **Stream State** (`core/stream_state.py`)
   - Add `SESSION_REVIEW` to `StreamType` enum

5. **Backend Service** (`service/session_manager_service.py`)
   - Add `review_session()` RPC
   - Add `approve_session_review()` RPC

6. **UI: Context Menu** (`SessionTreeView.tsx`)
   - Add session-level context menu
   - Wire up "Review & Summarize" option

7. **UI: Modal** (`components/SessionReviewModal/`)
   - Create `SessionReviewModal.tsx`
   - Create `SessionReviewModal.css`

8. **UI: Turn Renderer**
   - Add `SessionSummaryTurn` component for displaying in conversation

9. **Archiver** (`core/archiver.py`)
   - Add serialization/deserialization for `SessionSummaryBlock`

## Future Enhancements

- **Diff view**: Show what changed since last review
- **Auto-review**: Suggest review when session becomes long
- **Export**: Generate markdown/PDF report from review
- **Templates**: Different review templates for different session types
- **Review history**: Show all reviews for a session in a timeline
- **Cost tracking**: Show estimated cost for review by backend
- **Backend comparison**: Generate reviews with multiple backends side-by-side
