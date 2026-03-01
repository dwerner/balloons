/**
 * DiffView - Renders a diff with syntax highlighting and inline commenting
 *
 * Uses react-diff-viewer-continued for diff rendering with Prism syntax highlighting.
 *
 * Interaction modes:
 * - Desktop: Click for single line, drag (mousedown->mouseup) for range
 * - Mobile: Tap for single line, long-press to start range, then tap another line
 */

import React, { memo, useMemo, useState, useCallback, useDeferredValue, useRef, useEffect } from 'react';
import ReactDiffViewer, { DiffMethod } from 'react-diff-viewer-continued';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { DiffFile } from '../../../../generated/balloons-client';
import type { CodeReviewComment, ReviewState } from './types';
import { createLogger } from '../../utils/debugLog';
import { useTheme } from '../layout';
import { getLanguageFromPath } from '../StreamingTurnsView/cards/SyntaxHighlighter';

interface DiffViewProps {
  file: DiffFile;
  reviewState: ReviewState;
  onAddComment?: (comment: Omit<CodeReviewComment, 'id'>) => void;
  onEditComment?: (commentId: string, newText: string) => void;
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

/** Info extracted from a diff line */
interface LineInfo {
  lineNumber: number;
  side: 'L' | 'R';
  content: string;
}

// Long press duration in ms
const LONG_PRESS_MS = 400;

// Scoped logger
const log = createLogger('DiffView');

/** Extract line info from a DOM element within the diff viewer */
function extractLineInfo(element: HTMLElement): LineInfo | null {
  // Find the table row containing this element
  const row = element.closest('tr');
  if (!row) return null;

  // Look for line number cells - they have data attributes set by react-diff-viewer
  const gutterCells = row.querySelectorAll('td[class*="gutter"]');
  if (gutterCells.length === 0) return null;

  // In unified view, there are two gutter cells (old line, new line)
  // We'll use the right/new line number for comments
  let lineNumber: number | null = null;
  let side: 'L' | 'R' = 'R';

  // Check each gutter cell for a line number
  for (let i = gutterCells.length - 1; i >= 0; i--) {
    const cell = gutterCells[i];
    const text = cell?.textContent?.trim();
    if (text && /^\d+$/.test(text)) {
      lineNumber = parseInt(text, 10);
      side = i === 0 ? 'L' : 'R';
      break;
    }
  }

  if (lineNumber === null) return null;

  // Get the content from the code cell
  const codeCell = row.querySelector('td[class*="content"]');
  const content = codeCell?.textContent || '';

  return { lineNumber, side, content };
}

/** Get line info from event target */
function getLineInfoFromEvent(e: React.MouseEvent | React.TouchEvent): LineInfo | null {
  const target = e.target as HTMLElement;
  return extractLineInfo(target);
}

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

/** Comment widget displayed inline */
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
    : `Line ${comment.line_start}`;

  return (
    <div className="code-review-comment">
      <div className="code-review-comment__range">{rangeLabel}</div>
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

/** Reconstruct old and new content from our DiffFile format */
function reconstructContent(file: DiffFile): { oldContent: string; newContent: string } {
  const oldLines: string[] = [];
  const newLines: string[] = [];

  for (const hunk of file.hunks) {
    for (const change of hunk.changes) {
      if (change.type === 'delete') {
        oldLines.push(change.content);
      } else if (change.type === 'insert') {
        newLines.push(change.content);
      } else {
        // Normal/context line - appears in both
        oldLines.push(change.content);
        newLines.push(change.content);
      }
    }
  }

  return {
    oldContent: oldLines.join('\n'),
    newContent: newLines.join('\n'),
  };
}

export const DiffView = memo(function DiffView({
  file,
  reviewState,
  onAddComment,
  onEditComment,
  onDeleteComment,
}: DiffViewProps) {
  // Theme for syntax highlighting
  const { resolvedTheme: currentTheme } = useTheme();
  const resolvedTheme = useDeferredValue(currentTheme);
  const isLightTheme = resolvedTheme === 'light';

  // State
  const [commentForm, setCommentForm] = useState<CommentFormState | null>(null);
  // Range selection start (for mobile long-press flow)
  const [rangeStart, setRangeStart] = useState<LineInfo | null>(null);
  // Current drag start (for desktop drag flow)
  const [dragStart, setDragStart] = useState<LineInfo | null>(null);

  // Refs
  const diffContainerRef = useRef<HTMLDivElement>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressFired = useRef(false);
  const dragStartRef = useRef<LineInfo | null>(null);
  const rangeStartRef = useRef<LineInfo | null>(null);
  const touchMoved = useRef(false);

  // Get language for syntax highlighting
  const language = useMemo(() => getLanguageFromPath(file.path), [file.path]);

  // Reconstruct old/new content from hunks
  const { oldContent, newContent } = useMemo(() => reconstructContent(file), [file]);

  // Get comments for this file
  const fileComments = useMemo(() => {
    if (!reviewState.active || !reviewState.review) return [];
    return reviewState.review.comments.filter(
      c => c.file_path === file.absolutePath || c.file_path === file.path
    );
  }, [reviewState, file.absolutePath, file.path]);

  // Clear long press timer
  const clearLongPress = useCallback(() => {
    if (longPressTimer.current) {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }, []);

  // Open comment form
  const openCommentForm = useCallback((start: LineInfo, end?: LineInfo) => {
    log('openCommentForm', { start: start.lineNumber, end: end?.lineNumber });
    const hasRange = end && end.lineNumber !== start.lineNumber;
    const startLine = hasRange ? Math.min(start.lineNumber, end.lineNumber) : start.lineNumber;
    const endLine = hasRange ? Math.max(start.lineNumber, end.lineNumber) : undefined;

    setCommentForm({
      lineStart: startLine,
      lineEnd: endLine,
      content: hasRange ? [start.content, end.content] : [start.content],
    });

    // Clear selection state
    rangeStartRef.current = null;
    dragStartRef.current = null;
    setRangeStart(null);
    setDragStart(null);
  }, []);

  // Submit comment
  const handleSubmitComment = useCallback((text: string) => {
    if (!commentForm) return;

    if (commentForm.editingCommentId && onEditComment) {
      onEditComment(commentForm.editingCommentId, text);
    } else if (onAddComment) {
      onAddComment({
        file_path: file.absolutePath || file.path,
        line_start: commentForm.lineStart,
        line_end: commentForm.lineEnd,
        comment: text,
        context_type: 'diff',
        context_lines: commentForm.content,
        change_type: 'modify',
      });
    }

    setCommentForm(null);
  }, [commentForm, onAddComment, onEditComment, file]);

  // Start editing an existing comment
  const handleStartEdit = useCallback((comment: CodeReviewComment) => {
    setCommentForm({
      lineStart: comment.line_start,
      lineEnd: comment.line_end,
      content: comment.context_lines || [],
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

  // === DESKTOP: Mouse events for drag selection ===

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!reviewState.active) return;

    const lineInfo = getLineInfoFromEvent(e);
    if (!lineInfo) return;

    log('mouseDown', { line: lineInfo.lineNumber });
    dragStartRef.current = lineInfo;
    setDragStart(lineInfo);
  }, [reviewState.active]);

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    const currentDragStart = dragStartRef.current;
    if (!reviewState.active || !currentDragStart) return;

    const lineInfo = getLineInfoFromEvent(e);
    if (!lineInfo) {
      dragStartRef.current = null;
      setDragStart(null);
      return;
    }

    log('mouseUp', { start: currentDragStart.lineNumber, end: lineInfo.lineNumber });
    openCommentForm(currentDragStart, lineInfo);
  }, [reviewState.active, openCommentForm]);

  const handleMouseLeave = useCallback(() => {
    dragStartRef.current = null;
    setDragStart(null);
  }, []);

  // === MOBILE: Touch events for long-press range selection ===

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    if (!reviewState.active) return;

    const currentRangeStart = rangeStartRef.current;
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
  }, [reviewState.active, clearLongPress]);

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
  }, [clearLongPress, openCommentForm]);

  const handleTouchMove = useCallback(() => {
    touchMoved.current = true;
    clearLongPress();
  }, [clearLongPress]);

  // The line to highlight (either drag start on desktop or range start on mobile)
  const highlightLine = dragStart || rangeStart;

  // Build highlighted lines array for react-diff-viewer
  const highlightedLines = useMemo(() => {
    const lines: string[] = [];

    // Highlight lines from existing comments
    for (const comment of fileComments) {
      const start = comment.line_start;
      const end = comment.line_end || start;
      for (let i = start; i <= end; i++) {
        lines.push(`R-${i}`);
      }
    }

    // Highlight active selection
    if (commentForm) {
      const start = commentForm.lineStart;
      const end = commentForm.lineEnd || start;
      for (let i = start; i <= end; i++) {
        lines.push(`R-${i}`);
      }
    } else if (highlightLine) {
      lines.push(`R-${highlightLine.lineNumber}`);
    }

    return lines;
  }, [fileComments, commentForm, highlightLine]);

  // Apply custom highlighting via DOM manipulation for commented vs active lines
  useEffect(() => {
    if (!diffContainerRef.current) return;

    // Clear existing custom classes
    const existingHighlights = diffContainerRef.current.querySelectorAll('.diff-line--commented, .diff-line--in-range');
    existingHighlights.forEach(el => {
      el.classList.remove('diff-line--commented', 'diff-line--in-range', 'diff-line--range-start');
    });

    // Apply classes to commented lines
    for (const comment of fileComments) {
      const start = comment.line_start;
      const end = comment.line_end || start;
      for (let lineNum = start; lineNum <= end; lineNum++) {
        // Find rows with this line number
        const gutterCells = diffContainerRef.current.querySelectorAll('td[class*="gutter"]');
        gutterCells.forEach(cell => {
          const text = cell.textContent?.trim();
          if (text === String(lineNum)) {
            const row = cell.closest('tr');
            if (row) row.classList.add('diff-line--commented');
          }
        });
      }
    }

    // Apply classes to active selection
    if (commentForm || highlightLine) {
      const start = commentForm?.lineStart || highlightLine?.lineNumber || 0;
      const end = commentForm?.lineEnd || start;
      for (let lineNum = start; lineNum <= end; lineNum++) {
        const gutterCells = diffContainerRef.current.querySelectorAll('td[class*="gutter"]');
        gutterCells.forEach(cell => {
          const text = cell.textContent?.trim();
          if (text === String(lineNum)) {
            const row = cell.closest('tr');
            if (row) {
              row.classList.add('diff-line--in-range');
              if (lineNum === start) {
                row.classList.add('diff-line--range-start');
              }
            }
          }
        });
      }
    }
  }, [fileComments, commentForm, highlightLine]);

  // Syntax highlight renderer using Prism
  const renderContent = useCallback((content: string) => {
    return (
      <SyntaxHighlighter
        language={language}
        style={isLightTheme ? oneLight : oneDark}
        customStyle={{
          display: 'inline',
          padding: 0,
          margin: 0,
          background: 'transparent',
          fontSize: 'inherit',
          lineHeight: 'inherit',
        }}
        codeTagProps={{
          style: {
            display: 'inline',
            padding: 0,
            margin: 0,
            background: 'transparent',
            fontSize: 'inherit',
            lineHeight: 'inherit',
          }
        }}
        PreTag="span"
      >
        {content}
      </SyntaxHighlighter>
    );
  }, [language, isLightTheme]);

  // Render binary file
  if (file.isBinary) {
    return (
      <div className="code-diff-view code-diff-view--binary">
        <div className="code-diff-view__header">
          <span className="code-diff-view__path">{file.path}</span>
        </div>
        <p>Binary file not shown</p>
      </div>
    );
  }

  // Render empty diff
  if (file.hunks.length === 0) {
    return (
      <div className="code-diff-view code-diff-view--empty">
        <div className="code-diff-view__header">
          <span className="code-diff-view__path">{file.path}</span>
        </div>
        <p>No changes in this file</p>
      </div>
    );
  }

  const diffClasses = [
    'code-diff-view',
    reviewState.active ? 'code-diff-view--review-mode' : '',
    highlightLine ? 'code-diff-view--selecting' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={diffClasses}>
      <div className="code-diff-view__header">
        <span className="code-diff-view__path">{file.path}</span>
        <span className="code-diff-view__stats">
          <span className="code-diff-view__additions">+{file.additions}</span>
          <span className="code-diff-view__deletions">-{file.deletions}</span>
        </span>
      </div>

      <div
        ref={diffContainerRef}
        onMouseDown={handleMouseDown}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        onTouchMove={handleTouchMove}
      >
        <ReactDiffViewer
          oldValue={oldContent}
          newValue={newContent}
          splitView={false}
          useDarkTheme={!isLightTheme}
          renderContent={renderContent}
          highlightLines={highlightedLines}
          showDiffOnly={true}
          extraLinesSurroundingDiff={3}
          compareMethod={DiffMethod.LINES}
          styles={{
            variables: {
              dark: {
                diffViewerBackground: 'var(--color-bg)',
                diffViewerColor: 'var(--color-text)',
                addedBackground: 'rgba(74, 222, 128, 0.15)',
                addedColor: 'var(--color-text)',
                removedBackground: 'rgba(248, 113, 113, 0.15)',
                removedColor: 'var(--color-text)',
                wordAddedBackground: 'rgba(74, 222, 128, 0.3)',
                wordRemovedBackground: 'rgba(248, 113, 113, 0.3)',
                addedGutterBackground: 'rgba(74, 222, 128, 0.2)',
                removedGutterBackground: 'rgba(248, 113, 113, 0.2)',
                gutterBackground: 'var(--color-bg-secondary)',
                gutterBackgroundDark: 'var(--color-bg-secondary)',
                highlightBackground: 'rgba(59, 130, 246, 0.2)',
                highlightGutterBackground: 'rgba(59, 130, 246, 0.3)',
                codeFoldGutterBackground: 'var(--color-bg-secondary)',
                codeFoldBackground: 'var(--color-bg-secondary)',
                emptyLineBackground: 'var(--color-bg)',
                codeFoldContentColor: 'var(--color-text-secondary)',
              },
              light: {
                diffViewerBackground: 'var(--color-bg)',
                diffViewerColor: 'var(--color-text)',
                addedBackground: 'rgba(74, 222, 128, 0.15)',
                addedColor: 'var(--color-text)',
                removedBackground: 'rgba(248, 113, 113, 0.15)',
                removedColor: 'var(--color-text)',
                wordAddedBackground: 'rgba(74, 222, 128, 0.3)',
                wordRemovedBackground: 'rgba(248, 113, 113, 0.3)',
                addedGutterBackground: 'rgba(74, 222, 128, 0.2)',
                removedGutterBackground: 'rgba(248, 113, 113, 0.2)',
                gutterBackground: 'var(--color-bg-secondary)',
                gutterBackgroundDark: 'var(--color-bg-secondary)',
                highlightBackground: 'rgba(59, 130, 246, 0.2)',
                highlightGutterBackground: 'rgba(59, 130, 246, 0.3)',
                codeFoldGutterBackground: 'var(--color-bg-secondary)',
                codeFoldBackground: 'var(--color-bg-secondary)',
                emptyLineBackground: 'var(--color-bg)',
                codeFoldContentColor: 'var(--color-text-secondary)',
              },
            },
            diffContainer: {
              width: '100%',
              tableLayout: 'fixed' as const,
            },
            line: {
              fontSize: '12px',
              lineHeight: '1.5',
              fontFamily: "'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace",
            },
            content: {
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              width: '100%',
            },
            contentText: {
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
            },
            gutter: {
              minWidth: '40px',
              padding: '0 8px',
              cursor: reviewState.active ? 'pointer' : 'default',
            },
          }}
        />
      </div>

      {/* Comment form */}
      {commentForm && (
        <CommentForm
          onSubmit={handleSubmitComment}
          onCancel={handleCancelComment}
          lineRange={commentForm.lineEnd && commentForm.lineEnd !== commentForm.lineStart
            ? `${commentForm.lineStart}-${commentForm.lineEnd}`
            : String(commentForm.lineStart)}
          initialText={commentForm.initialText}
          isEditing={!!commentForm.editingCommentId}
        />
      )}

      {/* Existing comments */}
      {fileComments.length > 0 && (
        <div className="diff-comments-list">
          {fileComments.map(comment => (
            <CommentWidget
              key={comment.id}
              comment={comment}
              onEdit={() => handleStartEdit(comment)}
              onDelete={() => handleDelete(comment.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
});

export default DiffView;
