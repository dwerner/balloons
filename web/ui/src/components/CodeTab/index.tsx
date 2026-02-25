/**
 * CodeTab - Unified code review interface
 *
 * Shows unstaged git changes, allows inline commenting, and submits
 * structured code reviews to the chat.
 */

import React, { useState, useEffect, useCallback, useMemo, memo } from 'react';
import type { GitDiffResult, DiffFile, FileStateServiceClient } from '../../../../generated/balloons-client';
import type { ReviewState, CodeReview, CodeReviewComment } from './types';
import { FileList } from './FileList';
import { DiffView } from './DiffView';
import { useDialog } from '../Dialog';
import './CodeTab.css';

export interface CodeTabProps {
  /** Current working directory / git root */
  cwd?: string;
  /** FileStateService client for git operations */
  client?: FileStateServiceClient;
  /** Callback when a review is submitted */
  onSubmitReview?: (review: CodeReview) => void;
}

// Generate unique ID
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

// LocalStorage key for persisting review state
const REVIEW_STORAGE_KEY = 'balloons:code-review';

export const CodeTab = memo(function CodeTab({
  cwd,
  client,
  onSubmitReview,
}: CodeTabProps) {
  // Dialog hook for confirm/alert dialogs
  const { confirm, alert } = useDialog();

  // Diff state
  const [diffResult, setDiffResult] = useState<GitDiffResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Selected file
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  // Review state - initialize from localStorage if available
  const [reviewState, setReviewState] = useState<ReviewState>(() => {
    try {
      const saved = localStorage.getItem(REVIEW_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved) as ReviewState;
        // Validate structure
        if (parsed.active && parsed.review && Array.isArray(parsed.review.comments)) {
          return parsed;
        }
      }
    } catch {
      // Ignore parse errors
    }
    return { active: false, review: null };
  });

  // Show staged vs unstaged
  const [showStaged, setShowStaged] = useState(false);

  // Load diff when cwd changes or refresh is triggered
  const loadDiff = useCallback(async () => {
    if (!cwd || !client) {
      setDiffResult(null);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const result = await client.getGitDiff(cwd, showStaged);
      setDiffResult(result);

      // Auto-select first file if none selected
      if (result.files.length > 0 && !selectedFilePath && result.files[0]) {
        setSelectedFilePath(result.files[0].path);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      setDiffResult(null);
    } finally {
      setIsLoading(false);
    }
  }, [cwd, client, showStaged, selectedFilePath]);

  // Load diff on mount and when dependencies change
  useEffect(() => {
    loadDiff();
  }, [loadDiff]);

  // Persist review state to localStorage when it changes
  useEffect(() => {
    if (reviewState.active && reviewState.review) {
      localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(reviewState));
    } else {
      localStorage.removeItem(REVIEW_STORAGE_KEY);
    }
  }, [reviewState]);

  // Get the selected file
  const selectedFile = useMemo(() => {
    if (!diffResult || !selectedFilePath) return null;
    return diffResult.files.find((f) => f.path === selectedFilePath) || null;
  }, [diffResult, selectedFilePath]);

  // Handle file selection
  const handleSelectFile = useCallback((path: string) => {
    setSelectedFilePath(path);
  }, []);

  // Start a review
  const handleStartReview = useCallback(() => {
    setReviewState({
      active: true,
      review: {
        id: generateId(),
        comments: [],
        created_at: new Date().toISOString(),
      },
    });
  }, []);

  // Cancel a review
  const handleCancelReview = useCallback(async () => {
    if (reviewState.review && reviewState.review.comments.length > 0) {
      const confirmed = await confirm({
        title: 'Discard Review?',
        message: `You have ${reviewState.review.comments.length} comment${reviewState.review.comments.length > 1 ? 's' : ''} that will be lost.`,
        confirmText: 'Discard',
        cancelText: 'Keep Editing',
        variant: 'warning',
      });
      if (!confirmed) {
        return;
      }
    }
    setReviewState({ active: false, review: null });
  }, [reviewState, confirm]);

  // Add a comment to the review
  const handleAddComment = useCallback((comment: Omit<CodeReviewComment, 'id'>) => {
    if (!reviewState.active || !reviewState.review) return;

    const newComment: CodeReviewComment = {
      ...comment,
      id: generateId(),
    };

    setReviewState((prev) => ({
      ...prev,
      review: prev.review
        ? {
            ...prev.review,
            comments: [...prev.review.comments, newComment],
          }
        : null,
    }));
  }, [reviewState.active, reviewState.review]);

  // Edit an existing comment
  const handleEditComment = useCallback((commentId: string, newText: string) => {
    if (!reviewState.active || !reviewState.review) return;

    setReviewState((prev) => ({
      ...prev,
      review: prev.review
        ? {
            ...prev.review,
            comments: prev.review.comments.map((c) =>
              c.id === commentId ? { ...c, comment: newText } : c
            ),
          }
        : null,
    }));
  }, [reviewState.active, reviewState.review]);

  // Delete a comment
  const handleDeleteComment = useCallback((commentId: string) => {
    if (!reviewState.active || !reviewState.review) return;

    setReviewState((prev) => ({
      ...prev,
      review: prev.review
        ? {
            ...prev.review,
            comments: prev.review.comments.filter((c) => c.id !== commentId),
          }
        : null,
    }));
  }, [reviewState.active, reviewState.review]);

  // Submit a review
  const handleSubmitReview = useCallback(async () => {
    if (!reviewState.review) return;

    if (reviewState.review.comments.length === 0) {
      await alert({
        title: 'No Comments',
        message: 'Add at least one comment before submitting the review.',
      });
      return;
    }

    if (onSubmitReview) {
      onSubmitReview(reviewState.review);
    }

    // Clear review state
    setReviewState({ active: false, review: null });
  }, [reviewState, onSubmitReview, alert]);

  // Refresh diff
  const handleRefresh = useCallback(() => {
    // Clear selection if file no longer exists
    if (selectedFilePath && diffResult) {
      const stillExists = diffResult.files.some((f) => f.path === selectedFilePath);
      if (!stillExists) {
        setSelectedFilePath(null);
      }
    }
    loadDiff();
  }, [loadDiff, selectedFilePath, diffResult]);

  // Render loading state
  if (isLoading && !diffResult) {
    return (
      <div className="code-tab code-tab--loading">
        <div className="code-tab__spinner" />
        <span>Loading changes...</span>
      </div>
    );
  }

  // Render error state
  if (error) {
    return (
      <div className="code-tab code-tab--error">
        <div className="code-tab__error-icon">!</div>
        <div className="code-tab__error-message">{error}</div>
        <button className="code-tab__retry" onClick={handleRefresh}>
          Retry
        </button>
      </div>
    );
  }

  // Render no CWD state
  if (!cwd) {
    return (
      <div className="code-tab code-tab--empty">
        <p>No working directory set.</p>
        <p>Select a session with a working directory to view changes.</p>
      </div>
    );
  }

  // Render no client state
  if (!client) {
    return (
      <div className="code-tab code-tab--empty">
        <p>Connecting to server...</p>
      </div>
    );
  }

  // Count changes
  const totalAdditions = diffResult?.files.reduce((sum, f) => sum + f.additions, 0) || 0;
  const totalDeletions = diffResult?.files.reduce((sum, f) => sum + f.deletions, 0) || 0;

  return (
    <div className="code-tab">
      {/* Header / toolbar */}
      <div className="code-tab__header">
        <div className="code-tab__title">
          {showStaged ? 'Staged Changes' : 'Unstaged Changes'}
          {diffResult && (
            <span className="code-tab__stats">
              <span className="code-tab__additions">+{totalAdditions}</span>
              <span className="code-tab__deletions">-{totalDeletions}</span>
            </span>
          )}
        </div>
        <div className="code-tab__actions">
          {/* Toggle staged/unstaged */}
          <button
            className={`code-tab__toggle ${!showStaged ? 'code-tab__toggle--active' : ''}`}
            onClick={() => setShowStaged(false)}
            disabled={!diffResult?.hasUnstaged}
            title="Show unstaged changes"
          >
            Unstaged
          </button>
          <button
            className={`code-tab__toggle ${showStaged ? 'code-tab__toggle--active' : ''}`}
            onClick={() => setShowStaged(true)}
            disabled={!diffResult?.hasStaged}
            title="Show staged changes"
          >
            Staged
          </button>

          {/* Refresh */}
          <button
            className="code-tab__refresh"
            onClick={handleRefresh}
            disabled={isLoading}
            title="Refresh"
          >
            {isLoading ? '...' : 'Refresh'}
          </button>

          {/* Review actions */}
          {!reviewState.active ? (
            <button
              className="code-tab__start-review"
              onClick={handleStartReview}
              disabled={!diffResult || diffResult.files.length === 0}
            >
              Start Review
            </button>
          ) : (
            <>
              <button
                className="code-tab__cancel-review"
                onClick={handleCancelReview}
              >
                Cancel
              </button>
              <button
                className="code-tab__submit-review"
                onClick={handleSubmitReview}
              >
                Submit ({reviewState.review?.comments.length || 0})
              </button>
            </>
          )}
        </div>
      </div>

      {/* Review banner */}
      {reviewState.active && (
        <div className="code-tab__review-banner">
          Review in progress ({reviewState.review?.comments.length || 0} comments)
        </div>
      )}

      {/* Main content */}
      <div className="code-tab__content">
        {/* File list sidebar */}
        <div className="code-tab__sidebar">
          <FileList
            files={diffResult?.files || []}
            selectedPath={selectedFilePath}
            onSelectFile={handleSelectFile}
          />
        </div>

        {/* Diff view */}
        <div className="code-tab__main">
          {selectedFile ? (
            <DiffView
              file={selectedFile}
              reviewState={reviewState}
              onAddComment={handleAddComment}
              onEditComment={handleEditComment}
              onDeleteComment={handleDeleteComment}
            />
          ) : (
            <div className="code-tab__no-selection">
              {diffResult && diffResult.files.length > 0 ? (
                <p>Select a file to view changes</p>
              ) : (
                <p>No changes to display</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export default CodeTab;

// Re-export types
export type { CodeReview, CodeReviewComment, ReviewState } from './types';
