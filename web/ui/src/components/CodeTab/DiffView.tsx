/**
 * DiffView - Renders a diff using react-diff-view with inline commenting
 */

import React, { memo, useMemo, useState, useCallback } from 'react';
import { Diff, Hunk, parseDiff, Decoration, getChangeKey } from 'react-diff-view';
import type { DiffFile, DiffHunk, DiffChange } from '../../../../generated/balloons-client';
import type { CodeReviewComment, ReviewState } from './types';

// Import react-diff-view styles
import 'react-diff-view/style/index.css';

interface DiffViewProps {
  file: DiffFile;
  reviewState: ReviewState;
  onAddComment?: (comment: Omit<CodeReviewComment, 'id'>) => void;
}

/** State for the comment input form */
interface CommentFormState {
  lineKey: string;
  lineNumber: number;
  changeType: 'add' | 'delete' | 'context';
  content: string;
}

/** Inline comment input form */
function CommentForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState('');

  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (text.trim()) {
      onSubmit(text.trim());
    }
  }, [text, onSubmit]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onCancel();
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (text.trim()) {
        onSubmit(text.trim());
      }
    }
  }, [text, onSubmit, onCancel]);

  return (
    <form className="code-comment-form" onSubmit={handleSubmit}>
      <textarea
        className="code-comment-form__input"
        placeholder="Add a comment... (Cmd+Enter to submit, Esc to cancel)"
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
          Add Comment
        </button>
      </div>
    </form>
  );
}

/**
 * Convert our DiffFile format to react-diff-view's expected format.
 * react-diff-view expects unified diff text, but we have structured data,
 * so we'll reconstruct the diff text for parsing.
 */
function convertToUnifiedDiff(file: DiffFile): string {
  const lines: string[] = [];

  // File header
  const oldPath = file.oldPath || file.path;
  lines.push(`diff --git a/${oldPath} b/${file.path}`);

  // Mode/status lines
  if (file.status === 'added') {
    lines.push('new file mode 100644');
  } else if (file.status === 'deleted') {
    lines.push('deleted file mode 100644');
  }

  // Index line (fake)
  lines.push('index 0000000..1111111 100644');

  // --- and +++ lines
  if (file.status === 'added') {
    lines.push('--- /dev/null');
  } else {
    lines.push(`--- a/${oldPath}`);
  }

  if (file.status === 'deleted') {
    lines.push('+++ /dev/null');
  } else {
    lines.push(`+++ b/${file.path}`);
  }

  // Hunks
  for (const hunk of file.hunks) {
    lines.push(hunk.header);

    for (const change of hunk.changes) {
      if (change.type === 'insert') {
        lines.push(`+${change.content}`);
      } else if (change.type === 'delete') {
        lines.push(`-${change.content}`);
      } else {
        lines.push(` ${change.content}`);
      }
    }
  }

  return lines.join('\n');
}

export const DiffView = memo(function DiffView({
  file,
  reviewState,
  onAddComment,
}: DiffViewProps) {
  // State for comment form
  const [commentForm, setCommentForm] = useState<CommentFormState | null>(null);

  // Convert our structured diff to unified diff text for react-diff-view
  const diffText = useMemo(() => convertToUnifiedDiff(file), [file]);

  // Parse the diff text
  const parsedDiff = useMemo(() => {
    try {
      const diffs = parseDiff(diffText);
      return diffs[0]; // We only have one file
    } catch (e) {
      console.error('Failed to parse diff:', e);
      return null;
    }
  }, [diffText]);

  // Handle clicking to add a comment
  const handleLineClick = useCallback((change: any) => {
    if (!reviewState.active) return;

    // Determine line number and type
    const lineNumber = change.newLineNumber || change.oldLineNumber || 0;
    const changeType = change.isInsert ? 'add' : change.isDelete ? 'delete' : 'context';

    // Generate key for this line
    const lineKey = change.isInsert
      ? `I${change.newLineNumber}`
      : change.isDelete
      ? `D${change.oldLineNumber}`
      : `N${change.newLineNumber || change.oldLineNumber}`;

    setCommentForm({
      lineKey,
      lineNumber,
      changeType,
      content: change.content || '',
    });
  }, [reviewState.active]);

  // Handle submitting a comment
  const handleSubmitComment = useCallback((text: string) => {
    if (!commentForm || !onAddComment) return;

    onAddComment({
      file_path: file.absolutePath || file.path,
      line_start: commentForm.lineNumber,
      comment: text,
      context_type: 'diff',
      context_lines: [commentForm.content],
      change_type: commentForm.changeType === 'context' ? 'modify' : commentForm.changeType,
    });

    setCommentForm(null);
  }, [commentForm, onAddComment, file]);

  // Handle canceling comment form
  const handleCancelComment = useCallback(() => {
    setCommentForm(null);
  }, []);

  // Build widgets from review comments AND active comment form
  const widgets = useMemo(() => {
    const widgetMap: Record<string, React.ReactNode> = {};

    // Add existing comments
    if (reviewState.active && reviewState.review) {
      // Filter comments for this file
      const fileComments = reviewState.review.comments.filter(
        (c) => c.file_path === file.absolutePath || c.file_path === file.path
      );

      for (const comment of fileComments) {
        // Generate a key for the line
        const key = comment.change_type === 'add'
          ? `I${comment.line_start}`
          : comment.change_type === 'delete'
          ? `D${comment.line_start}`
          : `N${comment.line_start}`;

        // If there's already a widget at this key, append
        const existing = widgetMap[key];
        widgetMap[key] = (
          <>
            {existing}
            <div className="code-review-comment">
              <div className="code-review-comment__content">{comment.comment}</div>
            </div>
          </>
        );
      }
    }

    // Add comment form if active
    if (commentForm) {
      const existing = widgetMap[commentForm.lineKey];
      widgetMap[commentForm.lineKey] = (
        <>
          {existing}
          <CommentForm
            onSubmit={handleSubmitComment}
            onCancel={handleCancelComment}
          />
        </>
      );
    }

    return widgetMap;
  }, [reviewState, file.absolutePath, file.path, commentForm, handleSubmitComment, handleCancelComment]);

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

  // Build a map of changes by their key for click handling
  const changesByKey = useMemo(() => {
    const map: Record<string, any> = {};
    for (const hunk of parsedDiff?.hunks || []) {
      for (const change of hunk.changes) {
        const key = getChangeKey(change);
        map[key] = change;
      }
    }
    return map;
  }, [parsedDiff]);

  // Handle click on a diff line (for mobile - whole row clickable)
  const handleDiffClick = useCallback((e: React.MouseEvent) => {
    if (!reviewState.active) return;

    // Find the closest diff line row
    const target = e.target as HTMLElement;
    const row = target.closest('tr.diff-line');
    if (!row) return;

    // Get the change key from the row's data attribute or class
    // react-diff-view adds change info to rows
    const codeCell = row.querySelector('.diff-code');
    if (!codeCell) return;

    // Try to find the change from the row
    // The row has classes like diff-line-insert, diff-line-delete, diff-line-normal
    const isInsert = row.classList.contains('diff-line-insert');
    const isDelete = row.classList.contains('diff-line-delete');

    // Get line numbers from gutter cells
    const gutterCells = row.querySelectorAll('.diff-gutter');
    let oldLine: number | null = null;
    let newLine: number | null = null;

    gutterCells.forEach((cell, idx) => {
      const text = cell.textContent?.trim();
      if (text && /^\d+$/.test(text)) {
        const num = parseInt(text, 10);
        if (idx === 0) oldLine = num;
        else newLine = num;
      }
    });

    // Build the change key
    let lineKey: string;
    let lineNumber: number;
    let changeType: 'add' | 'delete' | 'context';

    if (isInsert && newLine) {
      lineKey = `I${newLine}`;
      lineNumber = newLine;
      changeType = 'add';
    } else if (isDelete && oldLine) {
      lineKey = `D${oldLine}`;
      lineNumber = oldLine;
      changeType = 'delete';
    } else {
      const ln = newLine || oldLine || 0;
      lineKey = `N${ln}`;
      lineNumber = ln;
      changeType = 'context';
    }

    // Get the code content
    const content = codeCell.textContent || '';

    setCommentForm({
      lineKey,
      lineNumber,
      changeType,
      content,
    });
  }, [reviewState.active]);

  return (
    <div className={`code-diff-view ${reviewState.active ? 'code-diff-view--review-mode' : ''}`}>
      <div className="code-diff-view__header">
        <span className="code-diff-view__path">{file.path}</span>
        <span className="code-diff-view__stats">
          <span className="code-diff-view__additions">+{file.additions}</span>
          <span className="code-diff-view__deletions">-{file.deletions}</span>
        </span>
      </div>
      {/* Wrap diff in clickable container for mobile */}
      <div onClick={handleDiffClick}>
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
