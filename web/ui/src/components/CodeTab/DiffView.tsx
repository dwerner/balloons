/**
 * DiffView - Renders a diff with syntax highlighting and inline commenting
 *
 * Uses react-diff-viewer-continued for diff rendering with Prism syntax highlighting.
 *
 * Interaction modes:
 * - Click on line number to add a comment on that line
 */

import React, { memo, useMemo, useState, useCallback, useDeferredValue } from 'react';
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

// Scoped logger
const log = createLogger('DiffView');

/** Inline comment input form */
function CommentForm({
  onSubmit,
  onCancel,
  lineNumber,
  initialText = '',
  isEditing = false,
}: {
  onSubmit: (text: string) => void;
  onCancel: () => void;
  lineNumber: number;
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
    <div className="diff-comment-form">
      <div className="diff-comment-form__header">Line {lineNumber}</div>
      <form onSubmit={handleSubmit}>
        <textarea
          className="diff-comment-form__input"
          placeholder={isEditing ? "Edit comment..." : "Add a comment... (Cmd+Enter to submit, Esc to cancel)"}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
          rows={3}
        />
        <div className="diff-comment-form__actions">
          <button type="button" className="diff-comment-form__cancel" onClick={onCancel}>
            Cancel
          </button>
          <button type="submit" className="diff-comment-form__submit" disabled={!text.trim()}>
            {isEditing ? 'Save' : 'Add Comment'}
          </button>
        </div>
      </form>
    </div>
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
  return (
    <div className="diff-comment-widget">
      <div className="diff-comment-widget__content">{comment.comment}</div>
      <div className="diff-comment-widget__actions">
        <button type="button" onClick={onEdit}>Edit</button>
        <button type="button" onClick={onDelete}>Delete</button>
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

  // State for comment form
  const [commentFormLine, setCommentFormLine] = useState<number | null>(null);
  const [editingComment, setEditingComment] = useState<CodeReviewComment | null>(null);

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

  // Highlighted lines from comments
  const highlightedLines = useMemo(() => {
    const lines: string[] = [];
    for (const comment of fileComments) {
      lines.push(`R-${comment.line_start}`);
    }
    if (commentFormLine !== null) {
      lines.push(`R-${commentFormLine}`);
    }
    return lines;
  }, [fileComments, commentFormLine]);

  // Handle line number click
  const handleLineNumberClick = useCallback((lineId: string) => {
    if (!reviewState.active) return;

    log('lineNumberClick', { lineId });
    // lineId format: "L-5" (left/old) or "R-5" (right/new)
    const match = lineId.match(/^([LR])-(\d+)$/);
    if (!match) return;

    const lineNumber = parseInt(match[2] || '0', 10);
    setCommentFormLine(lineNumber);
    setEditingComment(null);
  }, [reviewState.active]);

  // Submit comment
  const handleSubmitComment = useCallback((text: string) => {
    if (editingComment && onEditComment) {
      onEditComment(editingComment.id, text);
    } else if (commentFormLine !== null && onAddComment) {
      onAddComment({
        file_path: file.absolutePath || file.path,
        line_start: commentFormLine,
        comment: text,
        context_type: 'diff',
        context_lines: [],
        change_type: 'modify',
      });
    }
    setCommentFormLine(null);
    setEditingComment(null);
  }, [commentFormLine, editingComment, onAddComment, onEditComment, file]);

  // Cancel comment form
  const handleCancelComment = useCallback(() => {
    setCommentFormLine(null);
    setEditingComment(null);
  }, []);

  // Start editing a comment
  const handleStartEdit = useCallback((comment: CodeReviewComment) => {
    setEditingComment(comment);
    setCommentFormLine(comment.line_start);
  }, []);

  // Delete a comment
  const handleDeleteComment = useCallback((commentId: string) => {
    if (onDeleteComment) {
      onDeleteComment(commentId);
    }
  }, [onDeleteComment]);

  // Syntax highlight renderer using Prism
  const renderContent = useCallback((content: string) => {
    // Use Prism syntax highlighter
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

      <ReactDiffViewer
        oldValue={oldContent}
        newValue={newContent}
        splitView={false}
        useDarkTheme={!isLightTheme}
        renderContent={renderContent}
        onLineNumberClick={handleLineNumberClick}
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
          line: {
            fontSize: '12px',
            lineHeight: '1.5',
            fontFamily: "'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace",
          },
          gutter: {
            minWidth: '40px',
            padding: '0 8px',
            cursor: reviewState.active ? 'pointer' : 'default',
          },
        }}
      />

      {/* Comment form overlay */}
      {commentFormLine !== null && (
        <CommentForm
          onSubmit={handleSubmitComment}
          onCancel={handleCancelComment}
          lineNumber={commentFormLine}
          initialText={editingComment?.comment || ''}
          isEditing={!!editingComment}
        />
      )}

      {/* Existing comments */}
      {fileComments.length > 0 && (
        <div className="diff-comments-list">
          {fileComments.map(comment => (
            <div key={comment.id} className="diff-comment-row">
              <div className="diff-comment-row__line">Line {comment.line_start}</div>
              <CommentWidget
                comment={comment}
                onEdit={() => handleStartEdit(comment)}
                onDelete={() => handleDeleteComment(comment.id)}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

export default DiffView;
