/**
 * DiffView - Renders a diff using react-diff-view with inline commenting
 *
 * Interaction modes:
 * - Desktop: Click for single line, drag (mousedown->mouseup) for range
 * - Mobile: Tap for single line, long-press to start range, then tap another line to complete
 *
 * Supports syntax highlighting for known file types via refractor/Prism.
 */

import React, { memo, useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { Diff, Hunk, parseDiff, getChangeKey } from 'react-diff-view';
import type { DiffFile } from '../../../../generated/balloons-client';
import type { CodeReviewComment, ReviewState } from './types';
import { createLogger } from '../../utils/debugLog';

// NOTE: Syntax highlighting in diff view is not currently supported.
// react-diff-view's tokenize function is incompatible with refractor v5
// (which is required by react-syntax-highlighter). When react-diff-view
// updates to support newer refractor, we can enable syntax highlighting.

// Import react-diff-view styles
import 'react-diff-view/style/index.css';

interface DiffViewProps {
  file: DiffFile;
  reviewState: ReviewState;
  onAddComment?: (comment: Omit<CodeReviewComment, 'id'>) => void;
  onEditComment?: (commentId: string, newText: string) => void;
  onDeleteComment?: (commentId: string) => void;
}

/** State for the comment input form */
interface CommentFormState {
  lineKey: string;
  lineStart: number;
  lineEnd?: number;
  changeType: 'add' | 'delete' | 'context';
  content: string[];
  /** If editing an existing comment, its ID */
  editingCommentId?: string;
  /** If editing, the initial text */
  initialText?: string;
}

/** Info extracted from a diff line */
interface LineInfo {
  lineKey: string;
  lineNumber: number;
  changeType: 'add' | 'delete' | 'context';
  content: string;
}

// Long press duration in ms
const LONG_PRESS_MS = 400;

// Scoped logger - enable with localStorage.setItem('balloons:debug-enabled', 'true')
const log = createLogger('DiffView');

/** Extract line info from a DOM row */
function extractLineInfo(row: Element): LineInfo | null {
  const codeCell = row.querySelector('.diff-code');
  if (!codeCell) return null;

  const isInsert = row.classList.contains('diff-line-insert');
  const isDelete = row.classList.contains('diff-line-delete');

  const gutterCells = row.querySelectorAll('.diff-gutter');
  let oldLine: number | null = null;
  let newLine: number | null = null;

  // Debug: log raw gutter values
  const gutterTexts: string[] = [];
  gutterCells.forEach((cell, idx) => {
    const text = cell.textContent?.trim() || '';
    gutterTexts.push(text);
    if (text && /^\d+$/.test(text)) {
      const num = parseInt(text, 10);
      if (idx === 0) oldLine = num;
      else newLine = num;
    }
  });
  console.log('[extractLineInfo]', { gutterTexts, oldLine, newLine, isInsert, isDelete });

  let lineKey: string;
  let lineNumber: number;
  let changeType: 'add' | 'delete' | 'context';

  // Determine change type from line numbers (more reliable than CSS classes)
  // Insert: only newLine exists (oldLine is null/empty)
  // Delete: only oldLine exists (newLine is null/empty)
  // Normal: both exist
  const hasOld = oldLine !== null;
  const hasNew = newLine !== null;

  if (!hasOld && hasNew) {
    // Insert line - only new line number
    lineKey = `I${newLine}`;
    lineNumber = newLine!;
    changeType = 'add';
  } else if (hasOld && !hasNew) {
    // Delete line - only old line number
    lineKey = `D${oldLine}`;
    lineNumber = oldLine!;
    changeType = 'delete';
  } else if (hasOld && hasNew) {
    // Normal/context line - both line numbers exist
    // react-diff-view uses N${oldLineNumber} as the key
    lineKey = `N${oldLine}`;
    lineNumber = newLine!;
    changeType = 'context';
  } else {
    // Fallback - shouldn't happen
    return null;
  }

  console.log('[extractLineInfo] computed', { hasOld, hasNew, lineKey, lineNumber, changeType });

  return { lineKey, lineNumber, changeType, content: codeCell.textContent || '' };
}

/** Get line info from event target */
function getLineInfoFromEvent(e: React.MouseEvent | React.TouchEvent): LineInfo | null {
  const target = e.target as HTMLElement;
  const row = target.closest('tr.diff-line');
  if (!row) return null;
  return extractLineInfo(row);
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

/** Convert our DiffFile format to unified diff text */
function convertToUnifiedDiff(file: DiffFile): string {
  const lines: string[] = [];
  const oldPath = file.oldPath || file.path;

  lines.push(`diff --git a/${oldPath} b/${file.path}`);
  if (file.status === 'added') lines.push('new file mode 100644');
  else if (file.status === 'deleted') lines.push('deleted file mode 100644');

  lines.push('index 0000000..1111111 100644');
  lines.push(file.status === 'added' ? '--- /dev/null' : `--- a/${oldPath}`);
  lines.push(file.status === 'deleted' ? '+++ /dev/null' : `+++ b/${file.path}`);

  for (const hunk of file.hunks) {
    lines.push(hunk.header);
    for (const change of hunk.changes) {
      if (change.type === 'insert') lines.push(`+${change.content}`);
      else if (change.type === 'delete') lines.push(`-${change.content}`);
      else lines.push(` ${change.content}`);
    }
  }

  return lines.join('\n');
}

export const DiffView = memo(function DiffView({
  file,
  reviewState,
  onAddComment,
  onEditComment,
  onDeleteComment,
}: DiffViewProps) {
  // State
  const [commentForm, setCommentForm] = useState<CommentFormState | null>(null);
  // Range selection start (for mobile long-press flow)
  const [rangeStart, setRangeStart] = useState<LineInfo | null>(null);
  // Current drag start (for desktop drag flow) - shown as highlight during drag
  const [dragStart, setDragStart] = useState<LineInfo | null>(null);

  // Refs
  const diffContainerRef = useRef<HTMLDivElement>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const longPressFired = useRef(false);
  // Ref to track dragStart synchronously (state updates are async)
  const dragStartRef = useRef<LineInfo | null>(null);
  // Ref to track rangeStart synchronously
  const rangeStartRef = useRef<LineInfo | null>(null);
  // Track if touch moved (to distinguish tap from scroll)
  const touchMoved = useRef(false);

  // Parse diff
  const diffText = useMemo(() => convertToUnifiedDiff(file), [file]);
  const parsedDiff = useMemo(() => {
    try {
      const diffs = parseDiff(diffText);
      const parsed = diffs[0];
      // Debug: log what keys react-diff-view will expect
      if (parsed) {
        const allChanges = parsed.hunks.flatMap(h => h.changes);
        const sampleKeys = allChanges.slice(0, 5).map(c => {
          if (c.type === 'insert') return `I${c.lineNumber}`;
          if (c.type === 'delete') return `D${c.lineNumber}`;
          return `N${c.oldLineNumber}`;
        });
        log('parsedDiff: sample change keys', { sampleKeys, totalChanges: allChanges.length });
      }
      return parsed;
    } catch (e) {
      log('parseDiff: failed', { error: e });
      return null;
    }
  }, [diffText]);

  // Find the correct widget key by looking up the change in parsedDiff
  const findChangeKey = useCallback((lineInfo: LineInfo): string | null => {
    if (!parsedDiff) return null;

    for (const hunk of parsedDiff.hunks) {
      for (const change of hunk.changes) {
        // Match by line number and type
        const changeKey = getChangeKey(change);
        if (lineInfo.changeType === 'add' && change.type === 'insert' && change.lineNumber === lineInfo.lineNumber) {
          log('findChangeKey: matched insert', { lineNumber: lineInfo.lineNumber, changeKey });
          return changeKey;
        }
        if (lineInfo.changeType === 'delete' && change.type === 'delete' && change.lineNumber === lineInfo.lineNumber) {
          log('findChangeKey: matched delete', { lineNumber: lineInfo.lineNumber, changeKey });
          return changeKey;
        }
        if (lineInfo.changeType === 'context' && change.type === 'normal') {
          // For context lines, check both old and new line numbers
          if (change.newLineNumber === lineInfo.lineNumber || change.oldLineNumber === lineInfo.lineNumber) {
            log('findChangeKey: matched normal', { lineNumber: lineInfo.lineNumber, oldLineNumber: change.oldLineNumber, newLineNumber: change.newLineNumber, changeKey });
            return changeKey;
          }
        }
      }
    }
    log('findChangeKey: no match found', { lineInfo });
    return null;
  }, [parsedDiff]);

  // Open comment form
  const openCommentForm = useCallback((start: LineInfo, end?: LineInfo) => {
    log('openCommentForm', { start: start.lineNumber, end: end?.lineNumber });
    const hasRange = end && end.lineNumber !== start.lineNumber;
    const startLine = hasRange ? Math.min(start.lineNumber, end.lineNumber) : start.lineNumber;
    const endLine = hasRange ? Math.max(start.lineNumber, end.lineNumber) : undefined;

    // Look up the correct widget key from parsedDiff
    const targetLineInfo = hasRange
      ? (end!.lineNumber > start.lineNumber ? end! : start)
      : start;
    const targetKey = findChangeKey(targetLineInfo) || targetLineInfo.lineKey;

    log('openCommentForm - setting form', { startLine, endLine, targetKey, fallback: !findChangeKey(targetLineInfo) });
    setCommentForm({
      lineKey: targetKey,
      lineStart: startLine,
      lineEnd: endLine,
      changeType: start.changeType,
      content: hasRange ? [start.content, end.content] : [start.content],
    });
    // Clear both refs and state
    rangeStartRef.current = null;
    dragStartRef.current = null;
    setRangeStart(null);
    setDragStart(null);
  }, []);

  // Submit comment (handles both add and edit)
  const handleSubmitComment = useCallback((text: string) => {
    if (!commentForm) return;

    if (commentForm.editingCommentId && onEditComment) {
      // Editing an existing comment
      onEditComment(commentForm.editingCommentId, text);
    } else if (onAddComment) {
      // Adding a new comment
      onAddComment({
        file_path: file.absolutePath || file.path,
        line_start: commentForm.lineStart,
        line_end: commentForm.lineEnd,
        comment: text,
        context_type: 'diff',
        context_lines: commentForm.content,
        change_type: commentForm.changeType === 'context' ? 'modify' : commentForm.changeType,
        line_key: commentForm.lineKey,  // Store the react-diff-view key
      });
    }

    setCommentForm(null);
  }, [commentForm, onAddComment, onEditComment, file]);

  // Start editing an existing comment
  const handleStartEdit = useCallback((comment: CodeReviewComment) => {
    // Use stored line_key if available, otherwise compute
    const lineKey = comment.line_key || (() => {
      const targetLine = comment.line_end || comment.line_start;
      return comment.change_type === 'add'
        ? `I${targetLine}`
        : comment.change_type === 'delete'
        ? `D${targetLine}`
        : `N${targetLine}`;
    })();

    setCommentForm({
      lineKey,
      lineStart: comment.line_start,
      lineEnd: comment.line_end,
      changeType: comment.change_type === 'add' ? 'add' : comment.change_type === 'delete' ? 'delete' : 'context',
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

  // Cancel
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

  // === DESKTOP: Mouse events for drag selection ===

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Debug: always log, even if not in review mode
    console.log('[DiffView] mouseDown RAW', { active: reviewState.active, target: e.target });
    log('mouseDown', { active: reviewState.active });
    if (!reviewState.active) {
      log('mouseDown - NOT in review mode, returning');
      return;
    }
    const lineInfo = getLineInfoFromEvent(e);
    log('mouseDown lineInfo', lineInfo);
    if (!lineInfo) {
      log('mouseDown - no lineInfo found');
      return;
    }

    // Update both ref (sync) and state (for highlight)
    dragStartRef.current = lineInfo;
    setDragStart(lineInfo);
    log('dragStart set', { line: lineInfo.lineNumber });
  }, [reviewState.active]);

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    // Read from ref for synchronous access
    const currentDragStart = dragStartRef.current;
    log('mouseUp', { active: reviewState.active, dragStart: currentDragStart?.lineNumber });
    if (!reviewState.active || !currentDragStart) {
      log('mouseUp early return - no active or no dragStart');
      return;
    }

    const lineInfo = getLineInfoFromEvent(e);
    log('mouseUp lineInfo', lineInfo);
    if (!lineInfo) {
      log('mouseUp - no lineInfo, clearing dragStart');
      dragStartRef.current = null;
      setDragStart(null);
      return;
    }

    // Complete selection (could be single line if same, or range if different)
    log('mouseUp - opening form', { start: currentDragStart.lineNumber, end: lineInfo.lineNumber });
    openCommentForm(currentDragStart, lineInfo);
  }, [reviewState.active, openCommentForm]);

  const handleMouseLeave = useCallback(() => {
    log('mouseLeave - clearing dragStart');
    // Cancel drag if mouse leaves the container
    dragStartRef.current = null;
    setDragStart(null);
  }, []);

  // === MOBILE: Touch events for long-press range selection ===

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const currentRangeStart = rangeStartRef.current;
    log('touchStart', { active: reviewState.active, rangeStart: currentRangeStart?.lineNumber });
    if (!reviewState.active) return;
    const lineInfo = getLineInfoFromEvent(e);
    log('touchStart lineInfo', lineInfo);
    if (!lineInfo) return;

    longPressFired.current = false;
    touchMoved.current = false;  // Reset touch moved flag
    clearLongPress();

    // If already have range start selected, next tap completes
    if (currentRangeStart) {
      log('touchStart - rangeStart exists, letting touchEnd handle');
      return; // Let touchEnd handle it
    }

    // Start long press timer to enter range select mode
    log('touchStart - starting long press timer');
    longPressTimer.current = setTimeout(() => {
      log('longPress FIRED', { line: lineInfo.lineNumber });
      longPressFired.current = true;
      rangeStartRef.current = lineInfo;
      setRangeStart(lineInfo);
      if (navigator.vibrate) navigator.vibrate(50);
    }, LONG_PRESS_MS);
  }, [reviewState.active, clearLongPress]);

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const currentRangeStart = rangeStartRef.current;
    const didMove = touchMoved.current;
    log('touchEnd', { rangeStart: currentRangeStart?.lineNumber, longPressFired: longPressFired.current, didMove });
    clearLongPress();

    // If the user moved their finger (scrolling), don't open comment form
    if (didMove) {
      log('touchEnd - touch moved (scroll), ignoring');
      return;
    }

    const lineInfo = getLineInfoFromEvent(e);
    log('touchEnd lineInfo', lineInfo);
    if (!lineInfo) {
      log('touchEnd - no lineInfo');
      return;
    }

    // If we have a range start and this is NOT the long-press that just fired
    if (currentRangeStart && !longPressFired.current) {
      log('touchEnd - completing range', { start: currentRangeStart.lineNumber, end: lineInfo.lineNumber });
      e.preventDefault();
      openCommentForm(currentRangeStart, lineInfo);
      return;
    }

    // If long press just fired, don't do anything else (range mode just activated)
    if (longPressFired.current) {
      log('touchEnd - longPress just fired, staying in range mode');
      longPressFired.current = false;
      return;
    }

    // Short tap without range mode = single line comment
    if (!currentRangeStart) {
      log('touchEnd - short tap, single line comment');
      openCommentForm(lineInfo);
    }
  }, [clearLongPress, openCommentForm]);

  const handleTouchMove = useCallback(() => {
    log('touchMove - canceling long press, marking as moved');
    touchMoved.current = true;  // Mark that touch moved (scrolling)
    clearLongPress();
  }, [clearLongPress]);

  // The line to highlight (either drag start on desktop or range start on mobile)
  const highlightLine = dragStart || rangeStart;

  // Log state changes
  useEffect(() => {
    log('STATE', { dragStart: dragStart?.lineNumber, rangeStart: rangeStart?.lineNumber, highlightLine: highlightLine?.lineNumber });
  }, [dragStart, rangeStart, highlightLine]);

  // Collect all ranges that should be highlighted (existing comments + current selection/form)
  const highlightRanges = useMemo(() => {
    const ranges: Array<{ start: number; end: number; isActive: boolean }> = [];

    // Add ranges for existing comments
    if (reviewState.active && reviewState.review) {
      const fileComments = reviewState.review.comments.filter(
        (c) => c.file_path === file.absolutePath || c.file_path === file.path
      );
      for (const comment of fileComments) {
        ranges.push({
          start: comment.line_start,
          end: comment.line_end || comment.line_start,
          isActive: false,
        });
      }
    }

    // Add range for comment form (active selection)
    if (commentForm) {
      ranges.push({
        start: commentForm.lineStart,
        end: commentForm.lineEnd || commentForm.lineStart,
        isActive: true,
      });
    } else if (highlightLine) {
      // Selection in progress
      ranges.push({
        start: highlightLine.lineNumber,
        end: highlightLine.lineNumber,
        isActive: true,
      });
    }

    return ranges;
  }, [reviewState, file.absolutePath, file.path, commentForm, highlightLine]);

  // Effect to highlight all ranges
  useEffect(() => {
    if (!diffContainerRef.current) return;

    // Clear existing highlights
    const existingStart = diffContainerRef.current.querySelectorAll('.diff-line--range-start');
    existingStart.forEach(el => el.classList.remove('diff-line--range-start'));
    const existingInRange = diffContainerRef.current.querySelectorAll('.diff-line--in-range');
    existingInRange.forEach(el => el.classList.remove('diff-line--in-range'));
    const existingCommented = diffContainerRef.current.querySelectorAll('.diff-line--commented');
    existingCommented.forEach(el => el.classList.remove('diff-line--commented'));

    // Apply highlights for each range
    const rows = diffContainerRef.current.querySelectorAll('tr.diff-line');
    rows.forEach(row => {
      const info = extractLineInfo(row);
      if (!info) return;

      for (const range of highlightRanges) {
        const minLine = Math.min(range.start, range.end);
        const maxLine = Math.max(range.start, range.end);

        if (info.lineNumber >= minLine && info.lineNumber <= maxLine) {
          if (range.isActive) {
            // Active selection (form open or selecting)
            row.classList.add('diff-line--in-range');
            if (info.lineNumber === range.start) {
              row.classList.add('diff-line--range-start');
            }
          } else {
            // Existing comment
            row.classList.add('diff-line--commented');
          }
        }
      }
    });
  }, [highlightRanges]);

  // Build widgets
  const widgets = useMemo(() => {
    const widgetMap: Record<string, React.ReactNode> = {};

    if (reviewState.active && reviewState.review) {
      const fileComments = reviewState.review.comments.filter(
        (c) => c.file_path === file.absolutePath || c.file_path === file.path
      );

      for (const comment of fileComments) {
        // Skip the comment if we're currently editing it (form will show instead)
        if (commentForm?.editingCommentId === comment.id) continue;

        // Use stored line_key if available, otherwise compute (for backwards compatibility)
        const key = comment.line_key || (() => {
          const targetLine = comment.line_end || comment.line_start;
          return comment.change_type === 'add'
            ? `I${targetLine}`
            : comment.change_type === 'delete'
            ? `D${targetLine}`
            : `N${targetLine}`;
        })();

        log('widgets: adding comment', { id: comment.id, key, storedKey: comment.line_key, line_start: comment.line_start, line_end: comment.line_end });

        const existing = widgetMap[key];
        const rangeLabel = comment.line_end && comment.line_end !== comment.line_start
          ? `Lines ${comment.line_start}-${comment.line_end}`
          : null;

        widgetMap[key] = (
          <>
            {existing}
            <div className="code-review-comment">
              {rangeLabel && <div className="code-review-comment__range">{rangeLabel}</div>}
              <div className="code-review-comment__content">{comment.comment}</div>
              <div className="code-review-comment__actions">
                <button
                  type="button"
                  className="code-review-comment__edit"
                  onClick={() => handleStartEdit(comment)}
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="code-review-comment__delete"
                  onClick={() => handleDelete(comment.id)}
                >
                  Delete
                </button>
              </div>
            </div>
          </>
        );
      }
    }

    if (commentForm) {
      const existing = widgetMap[commentForm.lineKey];
      const lineRange = commentForm.lineEnd && commentForm.lineEnd !== commentForm.lineStart
        ? `${commentForm.lineStart}-${commentForm.lineEnd}`
        : undefined;

      log('widgets: adding CommentForm', { lineKey: commentForm.lineKey, widgetKeys: Object.keys(widgetMap), isEditing: !!commentForm.editingCommentId });

      widgetMap[commentForm.lineKey] = (
        <>
          {existing}
          <CommentForm
            onSubmit={handleSubmitComment}
            onCancel={handleCancelComment}
            lineRange={lineRange}
            initialText={commentForm.initialText}
            isEditing={!!commentForm.editingCommentId}
          />
        </>
      );
    }

    log('widgets: final map', { keys: Object.keys(widgetMap), commentFormKey: commentForm?.lineKey });
    return widgetMap;
  }, [reviewState, file.absolutePath, file.path, commentForm, handleSubmitComment, handleCancelComment, handleStartEdit, handleDelete]);

  // Render states
  if (!parsedDiff) {
    return (
      <div className="code-diff-view code-diff-view--error">
        <p>Failed to parse diff for {file.path}</p>
      </div>
    );
  }

  if (file.isBinary) {
    return (
      <div className="code-diff-view code-diff-view--binary">
        <p>Binary file not shown</p>
      </div>
    );
  }

  if (parsedDiff.hunks.length === 0) {
    return (
      <div className="code-diff-view code-diff-view--empty">
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
        {commentForm && (log('render: commentForm exists', { lineKey: commentForm.lineKey, widgetKeys: Object.keys(widgets) }), null)}
        <Diff
          viewType="unified"
          diffType={parsedDiff.type}
          hunks={parsedDiff.hunks}
          widgets={widgets}
          gutterType="default"
        >
          {(hunks) =>
            hunks.map((hunk) => (
              <Hunk key={hunk.content} hunk={hunk} />
            ))
          }
        </Diff>
      </div>
    </div>
  );
});

export default DiffView;
