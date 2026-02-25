/**
 * FileContentView - Displays file content with line selection for commenting
 *
 * Similar interaction modes to DiffView:
 * - Desktop: Click for single line, drag (mousedown->mouseup) for range
 * - Mobile: Tap for single line, long-press to start range, then tap another line
 *
 * Supports syntax highlighting for known file types via Prism.
 */

import React, { memo, useState, useCallback, useRef, useEffect, useMemo, useDeferredValue } from 'react';
import { Prism as PrismHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { CodeReviewComment, ReviewState } from './types';
import { createLogger } from '../../utils/debugLog';
import { useTheme } from '../layout';
import { getLanguageFromPath } from '../StreamingTurnsView/cards/SyntaxHighlighter';

interface FileContentViewProps {
  /** Absolute path to the file */
  filePath: string;
  /** File content as a string */
  content: string;
  /** Current review state with comments */
  reviewState: ReviewState;
  /** Callback to add a new comment */
  onAddComment?: (comment: Omit<CodeReviewComment, 'id'>) => void;
  /** Callback to edit an existing comment */
  onEditComment?: (commentId: string, newText: string) => void;
  /** Callback to delete a comment */
  onDeleteComment?: (commentId: string) => void;
}

/** State for the comment input form */
interface CommentFormState {
  lineStart: number;
  lineEnd?: number;
  content: string[];
  /** If editing an existing comment, its ID */
  editingCommentId?: string;
  /** If editing, the initial text */
  initialText?: string;
}

/** Info extracted from a line */
interface LineInfo {
  lineNumber: number;
  content: string;
}

// Long press duration in ms
const LONG_PRESS_MS = 400;

// Scoped logger
const log = createLogger('FileContentView');

// Custom dark theme for file viewer - matches the app's green-tinted UI
const customDarkTheme = {
  ...oneDark,
  'pre[class*="language-"]': {
    ...oneDark['pre[class*="language-"]'],
    background: 'transparent',
    margin: 0,
    padding: 0,
    fontSize: '12px',
    lineHeight: '1.5',
  },
  'code[class*="language-"]': {
    ...oneDark['code[class*="language-"]'],
    background: 'transparent',
    fontSize: '12px',
    lineHeight: '1.5',
  },
};

// Custom light theme
const customLightTheme = {
  ...oneLight,
  'pre[class*="language-"]': {
    ...oneLight['pre[class*="language-"]'],
    background: 'transparent',
    margin: 0,
    padding: 0,
    fontSize: '12px',
    lineHeight: '1.5',
  },
  'code[class*="language-"]': {
    ...oneLight['code[class*="language-"]'],
    background: 'transparent',
    fontSize: '12px',
    lineHeight: '1.5',
  },
};

/** Renders a single line with syntax highlighting */
const SyntaxHighlightedLine = memo(function SyntaxHighlightedLine({
  code,
  language,
  isLightTheme,
}: {
  code: string;
  language: string;
  isLightTheme: boolean;
}) {
  const theme = isLightTheme ? customLightTheme : customDarkTheme;

  // Empty lines need a space to maintain height
  if (!code) {
    return <pre style={{ margin: 0 }}>{' '}</pre>;
  }

  return (
    <PrismHighlighter
      style={theme}
      language={language}
      PreTag="span"
      customStyle={{
        display: 'inline',
        margin: 0,
        padding: 0,
        background: 'transparent',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
      }}
    >
      {code}
    </PrismHighlighter>
  );
});

/** Inline comment input form */
function CommentForm({
  onSubmit,
  onCancel,
  lineRange,
  initialText = '',
  isEditing = false,
}: {
  onSubmit: (text: string) => void;
  onCancel: () => void;
  lineRange?: string;
  initialText?: string;
  isEditing?: boolean;
}) {
  const [text, setText] = useState(initialText);

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (text.trim()) onSubmit(text.trim());
  }, [text, onSubmit]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onCancel();
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (text.trim()) onSubmit(text.trim());
    }
  }, [text, onSubmit, onCancel]);

  return (
    <form className="code-comment-form" onSubmit={handleSubmit}>
      {lineRange && <div className="code-comment-form__range">Lines {lineRange}</div>}
      <textarea
        className="code-comment-form__input"
        placeholder={isEditing ? "Edit comment..." : "Add a comment... (Cmd+Enter to submit, Esc to cancel)"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        autoFocus
        rows={3}
      />
      <div className="code-comment-form__actions">
        <button type="button" className="code-comment-form__cancel" onClick={onCancel}>
          Cancel
        </button>
        <button type="submit" className="code-comment-form__submit" disabled={!text.trim()}>
          {isEditing ? 'Save' : 'Add Comment'}
        </button>
      </div>
    </form>
  );
}

/** Existing comment display */
function CommentWidget({
  comment,
  onEdit,
  onDelete,
}: {
  comment: CodeReviewComment;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const rangeLabel = comment.line_end && comment.line_end !== comment.line_start
    ? `Lines ${comment.line_start}-${comment.line_end}`
    : null;

  return (
    <div className="code-review-comment">
      {rangeLabel && <div className="code-review-comment__range">{rangeLabel}</div>}
      <div className="code-review-comment__content">{comment.comment}</div>
      <div className="code-review-comment__actions">
        <button type="button" className="code-review-comment__edit" onClick={onEdit}>
          Edit
        </button>
        <button type="button" className="code-review-comment__delete" onClick={onDelete}>
          Delete
        </button>
      </div>
    </div>
  );
}

export const FileContentView = memo(function FileContentView({
  filePath,
  content,
  reviewState,
  onAddComment,
  onEditComment,
  onDeleteComment,
}: FileContentViewProps) {
  // Get current theme for syntax highlighting - use deferred value for non-blocking theme changes
  const { resolvedTheme: currentTheme } = useTheme();
  const resolvedTheme = useDeferredValue(currentTheme);
  const isLightTheme = resolvedTheme === 'light';

  // Parse content into lines
  const lines = useMemo(() => content.split('\n'), [content]);

  // State
  const [commentForm, setCommentForm] = useState<CommentFormState | null>(null);
  const [rangeStart, setRangeStart] = useState<LineInfo | null>(null);
  const [dragStart, setDragStart] = useState<LineInfo | null>(null);

  // Refs
  const containerRef = useRef<HTMLDivElement>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressFired = useRef(false);
  const dragStartRef = useRef<LineInfo | null>(null);
  const rangeStartRef = useRef<LineInfo | null>(null);
  const touchMoved = useRef(false);

  // Get line info from event
  const getLineInfoFromEvent = useCallback((e: React.MouseEvent | React.TouchEvent): LineInfo | null => {
    const target = e.target as HTMLElement;
    const row = target.closest('[data-line-number]');
    if (!row) return null;

    const lineNumber = parseInt(row.getAttribute('data-line-number') || '0', 10);
    if (lineNumber <= 0 || lineNumber > lines.length) return null;

    return {
      lineNumber,
      content: lines[lineNumber - 1] || '',
    };
  }, [lines]);

  // Open comment form
  const openCommentForm = useCallback((start: LineInfo, end?: LineInfo) => {
    log('openCommentForm', { start: start.lineNumber, end: end?.lineNumber });
    const hasRange = end && end.lineNumber !== start.lineNumber;
    const startLine = hasRange ? Math.min(start.lineNumber, end.lineNumber) : start.lineNumber;
    const endLine = hasRange ? Math.max(start.lineNumber, end.lineNumber) : undefined;

    // Get content for all lines in range
    const contentLines: string[] = [];
    const fromLine = startLine;
    const toLine = endLine || startLine;
    for (let i = fromLine; i <= toLine; i++) {
      contentLines.push(lines[i - 1] || '');
    }

    setCommentForm({
      lineStart: startLine,
      lineEnd: endLine,
      content: contentLines,
    });

    // Clear selection state
    rangeStartRef.current = null;
    dragStartRef.current = null;
    setRangeStart(null);
    setDragStart(null);
  }, [lines]);

  // Submit comment
  const handleSubmitComment = useCallback((text: string) => {
    if (!commentForm) return;

    if (commentForm.editingCommentId && onEditComment) {
      onEditComment(commentForm.editingCommentId, text);
    } else if (onAddComment) {
      onAddComment({
        file_path: filePath,
        line_start: commentForm.lineStart,
        line_end: commentForm.lineEnd,
        comment: text,
        context_type: 'file_reference',
        context_lines: commentForm.content,
      });
    }

    setCommentForm(null);
  }, [commentForm, onAddComment, onEditComment, filePath]);

  // Start editing an existing comment
  const handleStartEdit = useCallback((comment: CodeReviewComment) => {
    setCommentForm({
      lineStart: comment.line_start,
      lineEnd: comment.line_end,
      content: comment.context_lines,
      editingCommentId: comment.id,
      initialText: comment.comment,
    });
  }, []);

  // Delete a comment
  const handleDelete = useCallback((commentId: string) => {
    if (onDeleteComment) {
      onDeleteComment(commentId);
    }
  }, [onDeleteComment]);

  // Cancel comment form
  const handleCancelComment = useCallback(() => {
    setCommentForm(null);
    rangeStartRef.current = null;
    dragStartRef.current = null;
    setRangeStart(null);
    setDragStart(null);
  }, []);

  // Clear long press timer
  const clearLongPress = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }, []);

  // === DESKTOP: Mouse events ===
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!reviewState.active) return;
    const lineInfo = getLineInfoFromEvent(e);
    if (!lineInfo) return;

    dragStartRef.current = lineInfo;
    setDragStart(lineInfo);
    log('dragStart set', { line: lineInfo.lineNumber });
  }, [reviewState.active, getLineInfoFromEvent]);

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    const currentDragStart = dragStartRef.current;
    if (!reviewState.active || !currentDragStart) return;

    const lineInfo = getLineInfoFromEvent(e);
    if (!lineInfo) {
      dragStartRef.current = null;
      setDragStart(null);
      return;
    }

    openCommentForm(currentDragStart, lineInfo);
  }, [reviewState.active, getLineInfoFromEvent, openCommentForm]);

  const handleMouseLeave = useCallback(() => {
    dragStartRef.current = null;
    setDragStart(null);
  }, []);

  // === MOBILE: Touch events ===
  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const currentRangeStart = rangeStartRef.current;
    if (!reviewState.active) return;
    const lineInfo = getLineInfoFromEvent(e);
    if (!lineInfo) return;

    longPressFired.current = false;
    touchMoved.current = false;
    clearLongPress();

    if (currentRangeStart) {
      return; // Let touchEnd handle it
    }

    longPressTimer.current = setTimeout(() => {
      longPressFired.current = true;
      rangeStartRef.current = lineInfo;
      setRangeStart(lineInfo);
      if (navigator.vibrate) navigator.vibrate(50);
    }, LONG_PRESS_MS);
  }, [reviewState.active, getLineInfoFromEvent, clearLongPress]);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const currentRangeStart = rangeStartRef.current;
    const didMove = touchMoved.current;
    clearLongPress();

    if (didMove) return;

    const lineInfo = getLineInfoFromEvent(e);
    if (!lineInfo) return;

    if (currentRangeStart && !longPressFired.current) {
      e.preventDefault();
      openCommentForm(currentRangeStart, lineInfo);
      return;
    }

    if (longPressFired.current) {
      longPressFired.current = false;
      return;
    }

    if (!currentRangeStart) {
      openCommentForm(lineInfo);
    }
  }, [clearLongPress, getLineInfoFromEvent, openCommentForm]);

  const handleTouchMove = useCallback(() => {
    touchMoved.current = true;
    clearLongPress();
  }, [clearLongPress]);

  // Highlight line
  const highlightLine = dragStart || rangeStart;

  // Get comments for this file
  const fileComments = useMemo(() => {
    if (!reviewState.active || !reviewState.review) return [];
    return reviewState.review.comments.filter(c => c.file_path === filePath);
  }, [reviewState, filePath]);

  // Group comments by their end line (or start line if no end)
  const commentsByLine = useMemo(() => {
    const map = new Map<number, CodeReviewComment[]>();
    for (const comment of fileComments) {
      const line = comment.line_end || comment.line_start;
      const existing = map.get(line) || [];
      existing.push(comment);
      map.set(line, existing);
    }
    return map;
  }, [fileComments]);

  // Build highlight ranges
  const highlightRanges = useMemo(() => {
    const ranges: Array<{ start: number; end: number; isActive: boolean }> = [];

    // Existing comments
    for (const comment of fileComments) {
      ranges.push({
        start: comment.line_start,
        end: comment.line_end || comment.line_start,
        isActive: false,
      });
    }

    // Active selection
    if (commentForm) {
      ranges.push({
        start: commentForm.lineStart,
        end: commentForm.lineEnd || commentForm.lineStart,
        isActive: true,
      });
    } else if (highlightLine) {
      ranges.push({
        start: highlightLine.lineNumber,
        end: highlightLine.lineNumber,
        isActive: true,
      });
    }

    return ranges;
  }, [fileComments, commentForm, highlightLine]);

  // Check if a line is in any range
  const getLineHighlightClass = useCallback((lineNumber: number): string => {
    const classes: string[] = [];

    for (const range of highlightRanges) {
      const minLine = Math.min(range.start, range.end);
      const maxLine = Math.max(range.start, range.end);

      if (lineNumber >= minLine && lineNumber <= maxLine) {
        if (range.isActive) {
          classes.push('file-line--in-range');
          if (lineNumber === range.start) {
            classes.push('file-line--range-start');
          }
        } else {
          classes.push('file-line--commented');
        }
      }
    }

    return classes.join(' ');
  }, [highlightRanges]);

  // Get file name from path
  const fileName = filePath.split('/').pop() || filePath;
  const language = getLanguageFromPath(filePath);

  const viewClasses = [
    'file-content-view',
    reviewState.active ? 'file-content-view--review-mode' : '',
    highlightLine ? 'file-content-view--selecting' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={viewClasses}>
      <div className="file-content-view__header">
        <span className="file-content-view__path" title={filePath}>{filePath}</span>
        <span className="file-content-view__info">
          {lines.length} lines
          {language && <span className="file-content-view__lang">{language}</span>}
        </span>
      </div>
      <div
        ref={containerRef}
        className="file-content-view__content"
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        onTouchMove={handleTouchMove}
      >
        <table className="file-content-view__table">
          <tbody>
            {lines.map((line, index) => {
              const lineNumber = index + 1;
              const highlightClass = getLineHighlightClass(lineNumber);
              const commentsAtLine = commentsByLine.get(lineNumber) || [];
              const showForm = commentForm && (commentForm.lineEnd || commentForm.lineStart) === lineNumber;
              const isFormEditing = commentForm?.editingCommentId;

              return (
                <React.Fragment key={lineNumber}>
                  <tr
                    className={`file-line ${highlightClass}`}
                    data-line-number={lineNumber}
                  >
                    <td className="file-line__gutter">{lineNumber}</td>
                    <td className="file-line__code">
                      <SyntaxHighlightedLine
                        code={line}
                        language={language}
                        isLightTheme={isLightTheme}
                      />
                    </td>
                  </tr>
                  {/* Render comments at this line */}
                  {commentsAtLine.map(comment => (
                    // Skip if we're editing this comment
                    isFormEditing === comment.id ? null : (
                      <tr key={comment.id} className="file-line__widget-row">
                        <td colSpan={2}>
                          <CommentWidget
                            comment={comment}
                            onEdit={() => handleStartEdit(comment)}
                            onDelete={() => handleDelete(comment.id)}
                          />
                        </td>
                      </tr>
                    )
                  ))}
                  {/* Render comment form at this line */}
                  {showForm && (
                    <tr className="file-line__widget-row">
                      <td colSpan={2}>
                        <CommentForm
                          onSubmit={handleSubmitComment}
                          onCancel={handleCancelComment}
                          lineRange={commentForm.lineEnd && commentForm.lineEnd !== commentForm.lineStart
                            ? `${commentForm.lineStart}-${commentForm.lineEnd}`
                            : undefined}
                          initialText={commentForm.initialText}
                          isEditing={!!commentForm.editingCommentId}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
});

export default FileContentView;
