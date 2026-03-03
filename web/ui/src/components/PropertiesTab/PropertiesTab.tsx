/**
 * PropertiesTab - Display and manage session properties
 *
 * Shows:
 * - Session metadata (title, created, modified, backend, working directory)
 * - Context usage (tokens, percentage)
 * - Fork/parent relationships
 * - Watcher relationships (watching/watched by)
 * - Bindings (goal/plan/todo)
 * - Review & Summarize functionality
 *
 * Most fields are editable inline with save-on-change behavior.
 *
 * URL ROUTING: This is a session tab at #/sessions/:sessionId/properties
 * - Parent/child session links should navigate to #/sessions/:sessionId
 * - Binding links could navigate to #/goals/:goalId/plans/:planId/todos/:todoId
 * - See docs/url-routing.md for the full routing design
 */

import React, { useState, useCallback, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import type { SessionInfo } from '../../../../generated/balloons-client';
import { debugLog } from '../../utils/debugLog';
import './PropertiesTab.css';

// Local types until client is regenerated
export interface BackendInfo {
  name: string;
  displayName: string;
}

export interface SessionReview {
  summary_id: string;
  proposed_title: string;
  approved_title: string;
  markdown_content: string;
  work_done: string;
  files_modified: string[];
  decisions_made: string[];
  next_steps: string[];
  questions_raised: string[];
  turn_count_at_review: number;
  reviewed_at: string;
  reviewed_by_backend: string;
  status: 'pending' | 'approved' | 'rejected';
}

export interface PropertiesTabProps {
  session: SessionInfo | null;
  isConnected: boolean;
  // Backend selection
  availableBackends: BackendInfo[];
  // Review/summarize
  onStartReview?: (backendName: string) => Promise<void>;
  isGeneratingReview?: boolean;
  reviewStreamingText?: string;  // Live streaming text during generation
  currentReview?: SessionReview | null;
  existingReviews?: SessionReview[];
  onApproveReview?: (summaryId: string, title: string, markdown: string | null) => Promise<void>;
  // Session actions
  onRename?: (newTitle: string) => Promise<void>;
  onChangeBackend?: (backendName: string) => Promise<void>;
  onChangeWorkingDirectory?: (path: string) => Promise<void>;
}

function formatDate(isoString: string | undefined): string {
  if (!isoString) return '-';
  const date = new Date(isoString);
  if (isNaN(date.getTime())) return isoString;
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatTokens(tokens: number | undefined, contextWindow: number | undefined): string {
  if (tokens === undefined) return '-';
  const tokensK = (tokens / 1000).toFixed(1);
  if (contextWindow) {
    const pct = ((tokens / contextWindow) * 100).toFixed(1);
    const windowK = (contextWindow / 1000).toFixed(0);
    return `${tokensK}k / ${windowK}k (${pct}%)`;
  }
  return `${tokensK}k`;
}

// Convert structured review to markdown for editing
function formatReviewAsMarkdown(review: SessionReview): string {
  const sections: string[] = [];

  if (review.work_done) {
    sections.push(`## Summary\n\n${review.work_done}`);
  }

  if (review.files_modified && review.files_modified.length > 0) {
    const items = review.files_modified.map(f => `- ${f}`).join('\n');
    sections.push(`## Files Modified\n\n${items}`);
  }

  if (review.decisions_made && review.decisions_made.length > 0) {
    const items = review.decisions_made.map(d => `- ${d}`).join('\n');
    sections.push(`## Decisions Made\n\n${items}`);
  }

  if (review.next_steps && review.next_steps.length > 0) {
    const items = review.next_steps.map(n => `- ${n}`).join('\n');
    sections.push(`## Next Steps\n\n${items}`);
  }

  if (review.questions_raised && review.questions_raised.length > 0) {
    const items = review.questions_raised.map(q => `- ${q}`).join('\n');
    sections.push(`## Open Questions\n\n${items}`);
  }

  return sections.join('\n\n') || review.markdown_content || '';
}

/**
 * Inline editable text field - saves on blur or Enter, cancels on Escape
 */
function EditableField({
  value,
  placeholder,
  onSave,
  mono = false,
  disabled = false,
}: {
  value: string;
  placeholder?: string;
  onSave: (newValue: string) => Promise<void>;
  mono?: boolean;
  disabled?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(value);
  const [isSaving, setIsSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Sync with external value changes
  useEffect(() => {
    if (!isEditing) {
      setEditValue(value);
    }
  }, [value, isEditing]);

  const handleSave = useCallback(async () => {
    const trimmed = editValue.trim();
    if (trimmed !== value && trimmed !== '') {
      setIsSaving(true);
      try {
        await onSave(trimmed);
      } finally {
        setIsSaving(false);
      }
    }
    setIsEditing(false);
  }, [editValue, value, onSave]);

  const handleCancel = useCallback(() => {
    setEditValue(value);
    setIsEditing(false);
  }, [value]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSave();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      handleCancel();
    }
  }, [handleSave, handleCancel]);

  const handleClick = useCallback(() => {
    if (!disabled) {
      setIsEditing(true);
      // Focus input after render
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [disabled]);

  if (isEditing) {
    return (
      <input
        ref={inputRef}
        type="text"
        className={`editable-field__input ${mono ? 'editable-field__input--mono' : ''}`}
        value={editValue}
        onChange={e => setEditValue(e.target.value)}
        onBlur={handleSave}
        onKeyDown={handleKeyDown}
        disabled={isSaving}
        placeholder={placeholder}
        autoFocus
      />
    );
  }

  return (
    <span
      className={`editable-field ${mono ? 'editable-field--mono' : ''} ${disabled ? 'editable-field--disabled' : ''}`}
      onClick={handleClick}
      title={disabled ? undefined : 'Click to edit'}
    >
      {value || <span className="editable-field__placeholder">{placeholder || '-'}</span>}
      {!disabled && <span className="editable-field__icon">✎</span>}
    </span>
  );
}

/**
 * Inline editable select field - saves on change
 */
function EditableSelect({
  value,
  options,
  onSave,
  disabled = false,
}: {
  value: string;
  options: { value: string; label: string }[];
  onSave: (newValue: string) => Promise<void>;
  disabled?: boolean;
}) {
  const [isSaving, setIsSaving] = useState(false);

  const handleChange = useCallback(async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newValue = e.target.value;
    if (newValue !== value) {
      setIsSaving(true);
      try {
        await onSave(newValue);
      } finally {
        setIsSaving(false);
      }
    }
  }, [value, onSave]);

  return (
    <select
      className="editable-select"
      value={value}
      onChange={handleChange}
      disabled={disabled || isSaving}
    >
      {options.map(opt => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

export function PropertiesTab({
  session,
  isConnected,
  availableBackends,
  onStartReview,
  isGeneratingReview = false,
  reviewStreamingText = '',
  currentReview,
  existingReviews = [],
  onApproveReview,
  onRename,
  onChangeBackend,
  onChangeWorkingDirectory,
}: PropertiesTabProps) {
  const [selectedReviewBackend, setSelectedReviewBackend] = useState('');

  // Review editing state
  const [isEditingReview, setIsEditingReview] = useState(false);
  const [editedTitle, setEditedTitle] = useState('');
  const [editedMarkdown, setEditedMarkdown] = useState('');

  // Initialize backend selection when backends load
  useEffect(() => {
    debugLog('PropertiesTab', 'backend init useEffect', {
      backendsCount: availableBackends.length,
      backends: availableBackends.map(b => b.name),
      selectedReviewBackend,
      sessionBackend: session?.backendName
    });
    if (availableBackends.length > 0 && !selectedReviewBackend) {
      const firstBackend = availableBackends[0];
      const newBackend = session?.backendName || (firstBackend ? firstBackend.name : '');
      debugLog('PropertiesTab', 'setting selectedReviewBackend', { newBackend });
      setSelectedReviewBackend(newBackend);
    }
  }, [availableBackends, session?.backendName, selectedReviewBackend]);

  // Initialize review editing when a new review arrives
  useEffect(() => {
    if (currentReview) {
      setEditedTitle(currentReview.proposed_title);
      setEditedMarkdown(currentReview.markdown_content || formatReviewAsMarkdown(currentReview));
    }
  }, [currentReview]);

  const handleStartReview = useCallback(async () => {
    debugLog('PropertiesTab', 'handleStartReview called', { hasOnStartReview: !!onStartReview, selectedReviewBackend });
    if (onStartReview && selectedReviewBackend) {
      debugLog('PropertiesTab', 'handleStartReview: calling onStartReview');
      await onStartReview(selectedReviewBackend);
    } else {
      debugLog('PropertiesTab', 'handleStartReview: skipped', { hasOnStartReview: !!onStartReview, selectedReviewBackend });
    }
  }, [onStartReview, selectedReviewBackend]);

  const handleApproveReview = useCallback(async () => {
    if (onApproveReview && currentReview) {
      await onApproveReview(
        currentReview.summary_id,
        editedTitle,
        isEditingReview ? editedMarkdown : null
      );
      setIsEditingReview(false);
    }
  }, [onApproveReview, currentReview, editedTitle, editedMarkdown, isEditingReview]);

  if (!isConnected) {
    return (
      <div className="properties-tab properties-tab--disconnected">
        <div className="empty-state">
          <h2>Not Connected</h2>
          <p>Connect to server to view session properties.</p>
        </div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="properties-tab properties-tab--no-session">
        <div className="empty-state">
          <h2>No Session Selected</h2>
          <p>Select a session to view its properties.</p>
        </div>
      </div>
    );
  }

  const currentBackend = session.backendName || session.model || '';
  const hasBackends = availableBackends.length > 0;

  return (
    <div className="properties-tab">
      {/* Session Metadata Section */}
      <section className="properties-section">
        <h3 className="properties-section__title">Session Info</h3>
        <div className="properties-grid">
          <div className="property-row">
            <span className="property-label">Title</span>
            <span className="property-value">
              {onRename ? (
                <EditableField
                  value={session.forkName || session.title || ''}
                  placeholder={`Session ${session.id.slice(0, 8)}`}
                  onSave={onRename}
                />
              ) : (
                session.forkName || session.title || `Session ${session.id.slice(0, 8)}`
              )}
            </span>
          </div>
          <div className="property-row">
            <span className="property-label">ID</span>
            <span className="property-value property-value--mono property-value--readonly">
              {session.id}
            </span>
          </div>
          <div className="property-row">
            <span className="property-label">Created</span>
            <span className="property-value property-value--readonly">
              {formatDate(session.created)}
            </span>
          </div>
          <div className="property-row">
            <span className="property-label">Modified</span>
            <span className="property-value property-value--readonly">
              {formatDate(session.lastModified)}
            </span>
          </div>
          <div className="property-row">
            <span className="property-label">Working Directory</span>
            <span className="property-value">
              {onChangeWorkingDirectory ? (
                <EditableField
                  value={session.workingDirectory || ''}
                  placeholder="Set working directory..."
                  onSave={onChangeWorkingDirectory}
                  mono
                />
              ) : (
                <span className="property-value--mono">{session.workingDirectory || '-'}</span>
              )}
            </span>
          </div>
          <div className="property-row">
            <span className="property-label">Messages</span>
            <span className="property-value property-value--readonly">{session.messageCount}</span>
          </div>
          <div className="property-row">
            <span className="property-label">Context</span>
            <span className="property-value property-value--readonly">
              {formatTokens(session.cachedContextTokens, session.contextWindow)}
            </span>
          </div>
        </div>
      </section>

      {/* Backend Section */}
      <section className="properties-section">
        <h3 className="properties-section__title">Backend</h3>
        <div className="properties-grid">
          <div className="property-row">
            <span className="property-label">Model</span>
            <span className="property-value">
              {onChangeBackend && hasBackends ? (
                <EditableSelect
                  value={currentBackend}
                  options={availableBackends.map(b => ({ value: b.name, label: b.displayName || b.name }))}
                  onSave={onChangeBackend}
                />
              ) : (
                currentBackend || '-'
              )}
            </span>
          </div>
        </div>
      </section>

      {/* Relationships Section */}
      {(session.parentId || session.bindingIndicator || (session.forkStatus && session.forkStatus !== 'none')) && (
        <section className="properties-section">
          <h3 className="properties-section__title">Relationships</h3>
          <div className="properties-grid">
            {session.parentId && (
              <div className="property-row">
                <span className="property-label">Parent Session</span>
                <span className="property-value property-value--mono property-value--readonly">
                  {session.parentId.slice(0, 8)}
                </span>
              </div>
            )}
            {session.forkStatus && session.forkStatus !== 'none' && (
              <div className="property-row">
                <span className="property-label">Fork Status</span>
                <span className="property-value property-value--readonly">{session.forkStatus}</span>
              </div>
            )}
            {session.bindingIndicator && (
              <div className="property-row">
                <span className="property-label">Binding</span>
                <span className="property-value property-value--readonly">{session.bindingIndicator}</span>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Review & Summarize Section */}
      <section className="properties-section">
        <h3 className="properties-section__title">Review &amp; Summarize</h3>
        <div className="review-section">
          <div className="review-controls">
            <select
              value={selectedReviewBackend}
              onChange={e => setSelectedReviewBackend(e.target.value)}
              disabled={isGeneratingReview || !hasBackends}
              className="editable-select"
            >
              {!hasBackends && <option value="">Loading backends...</option>}
              {availableBackends.map(b => (
                <option key={b.name} value={b.name}>{b.displayName || b.name}</option>
              ))}
            </select>
            <button
              onClick={() => {
                debugLog('PropertiesTab', 'Generate Summary button clicked', {
                  isGeneratingReview,
                  selectedReviewBackend,
                  hasOnStartReview: !!onStartReview,
                  willBeDisabled: isGeneratingReview || !selectedReviewBackend || !onStartReview
                });
                handleStartReview();
              }}
              disabled={isGeneratingReview || !selectedReviewBackend || !onStartReview}
              className="btn btn-primary"
            >
              {isGeneratingReview ? 'Generating...' : 'Generate Summary'}
            </button>
          </div>

          {/* Show streaming text while generating */}
          {isGeneratingReview && reviewStreamingText && (
            <div className="streaming-review">
              <div className="streaming-header">
                <h4>Generating Summary...</h4>
                <span className="streaming-indicator">●</span>
              </div>
              <div className="streaming-content">
                <pre>{reviewStreamingText}</pre>
              </div>
            </div>
          )}

          {currentReview && (
            <div className="current-review">
              <div className="review-header">
                <h4>Generated Summary</h4>
                <div className="review-mode-toggle">
                  <button
                    type="button"
                    className={`toggle-btn ${!isEditingReview ? 'active' : ''}`}
                    onClick={() => setIsEditingReview(false)}
                  >
                    Preview
                  </button>
                  <button
                    type="button"
                    className={`toggle-btn ${isEditingReview ? 'active' : ''}`}
                    onClick={() => setIsEditingReview(true)}
                  >
                    Edit
                  </button>
                </div>
              </div>

              <div className="review-title-field">
                <label>Title</label>
                <input
                  type="text"
                  value={editedTitle}
                  onChange={e => setEditedTitle(e.target.value)}
                  className="review-title-input"
                  placeholder="Session title..."
                />
              </div>

              <div className="review-body">
                {isEditingReview ? (
                  <textarea
                    value={editedMarkdown}
                    onChange={e => setEditedMarkdown(e.target.value)}
                    className="review-editor"
                    spellCheck={false}
                    placeholder="# Summary&#10;&#10;Describe what was accomplished..."
                  />
                ) : (
                  <div className="review-preview">
                    <ReactMarkdown>{editedMarkdown}</ReactMarkdown>
                  </div>
                )}
              </div>

              <div className="review-meta">
                <span>Generated by {currentReview.reviewed_by_backend}</span>
                <span className="meta-separator">•</span>
                <span>At turn {currentReview.turn_count_at_review}</span>
              </div>

              {onApproveReview && (
                <div className="review-actions">
                  <button
                    onClick={handleApproveReview}
                    className="btn btn-primary"
                    disabled={!editedTitle.trim()}
                  >
                    Approve &amp; Save
                  </button>
                </div>
              )}
            </div>
          )}

          {existingReviews.length > 0 && (
            <div className="past-reviews">
              <h4>Past Reviews ({existingReviews.length})</h4>
              <ul className="review-list">
                {existingReviews.map(r => (
                  <li key={r.summary_id} className="review-item">
                    <span className="review-date">{formatDate(r.reviewed_at)}</span>
                    <span className="review-backend">{r.reviewed_by_backend}</span>
                    {r.status === 'approved' && <span className="review-badge">&#x2713;</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!currentReview && existingReviews.length === 0 && !isGeneratingReview && (
            <p className="review-hint">
              Generate a summary to capture what was accomplished in this session.
            </p>
          )}
        </div>
      </section>

      {/* Status indicators */}
      <section className="properties-section properties-section--status">
        <div className="status-badges">
          {session.isStreaming && <span className="status-badge status-badge--streaming">Streaming</span>}
          {session.isPinned && <span className="status-badge status-badge--pinned">Pinned</span>}
        </div>
      </section>
    </div>
  );
}

export default PropertiesTab;
