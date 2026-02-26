/**
 * CodeTab - Unified code context interface
 *
 * Provides two sub-views:
 * - Changes: Shows unstaged git diff, allows inline commenting
 * - Files: Browse any file, select line ranges as context
 *
 * Comments accumulate and can be submitted to chat at any time.
 * Selection is always enabled - no separate "review mode" needed.
 */

import React, { useState, useEffect, useCallback, useMemo, memo, useImperativeHandle, forwardRef } from 'react';
import type { GitDiffResult, FileStateServiceClient } from '../../../../generated/balloons-client';
import type { CodeReview, CodeReviewComment } from './types';
import { FileList } from './FileList';
import { DiffView } from './DiffView';
import { OpenFilesList, type OpenFile } from './OpenFilesList';
import { FileContentView } from './FileContentView';
import { CommitModal } from '../CommitModal';
import { useDialog } from '../Dialog';
import { createLogger } from '../../utils/debugLog';
import './CodeTab.css';

const log = createLogger('CodeTab');

// Size threshold for warning (500KB)
const LARGE_FILE_THRESHOLD = 500 * 1024;

// LocalStorage keys
const COMMENTS_STORAGE_KEY = 'balloons:code-comments';
const OLD_REVIEW_STORAGE_KEY = 'balloons:code-review';
const OPEN_FILES_STORAGE_KEY = 'balloons:code-open-files';

/** Git status info for parent components */
export interface GitStatusInfo {
  hasUnstaged: boolean;
  hasStaged: boolean;
  fileCount: number;
}

export interface CodeTabProps {
  /** Current working directory / git root */
  cwd?: string;
  /** FileStateService client for git operations */
  client?: FileStateServiceClient;
  /** Callback when a review is submitted */
  onSubmitReview?: (review: CodeReview) => void;
  /** Callback to generate AI commit message - receives staged files and returns message */
  onRequestAICommitMessage?: (gitRoot: string, stagedDiff: string) => Promise<string>;
  /** Callback when git status changes (for showing badge on Code tab) */
  onGitStatusChange?: (status: GitStatusInfo | null) => void;
}

/** Handle exposed to parent for external control */
export interface CodeTabHandle {
  /** Open a file in the Files tab */
  openFile: (path: string) => Promise<void>;
}

// Sub-tab type
type CodeSubTab = 'changes' | 'files';

// Generate unique ID
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

// Helper to load comments from localStorage
function loadComments(): CodeReviewComment[] {
  try {
    // Try new format first
    const saved = localStorage.getItem(COMMENTS_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        return parsed;
      }
    }

    // Try migrating from old format
    const oldSaved = localStorage.getItem(OLD_REVIEW_STORAGE_KEY);
    if (oldSaved) {
      const parsed = JSON.parse(oldSaved);
      if (parsed && parsed.review && Array.isArray(parsed.review.comments)) {
        // Migrate to new format
        localStorage.setItem(COMMENTS_STORAGE_KEY, JSON.stringify(parsed.review.comments));
        localStorage.removeItem(OLD_REVIEW_STORAGE_KEY);
        return parsed.review.comments;
      }
    }
  } catch {
    // Ignore parse errors
  }
  return [];
}

// Helper to save comments to localStorage
function saveComments(comments: CodeReviewComment[]): void {
  if (comments.length > 0) {
    localStorage.setItem(COMMENTS_STORAGE_KEY, JSON.stringify(comments));
  } else {
    localStorage.removeItem(COMMENTS_STORAGE_KEY);
  }
}

// Helper to load open files from localStorage
function loadOpenFiles(): OpenFile[] {
  try {
    const saved = localStorage.getItem(OPEN_FILES_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed)) {
        return parsed;
      }
    }
  } catch {
    // Ignore
  }
  return [];
}

// Helper to save open files to localStorage
function saveOpenFiles(files: OpenFile[]): void {
  if (files.length > 0) {
    localStorage.setItem(OPEN_FILES_STORAGE_KEY, JSON.stringify(files));
  } else {
    localStorage.removeItem(OPEN_FILES_STORAGE_KEY);
  }
}

// Check if content appears to be binary
function isBinaryContent(content: string): boolean {
  // Check for null bytes or high concentration of non-printable characters
  const sampleSize = Math.min(content.length, 8000);
  let nonPrintable = 0;
  for (let i = 0; i < sampleSize; i++) {
    const code = content.charCodeAt(i);
    if (code === 0) return true; // Null byte = definitely binary
    if (code < 32 && code !== 9 && code !== 10 && code !== 13) {
      nonPrintable++;
    }
  }
  // If more than 10% non-printable, likely binary
  return nonPrintable / sampleSize > 0.1;
}

// Format file size for display
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export const CodeTab = memo(forwardRef<CodeTabHandle, CodeTabProps>(function CodeTab({
  cwd,
  client,
  onSubmitReview,
  onRequestAICommitMessage,
  onGitStatusChange,
}, ref) {
  // Dialog hook for confirm/alert dialogs
  const { confirm, alert } = useDialog();

  // Sub-tab state
  const [activeSubTab, setActiveSubTab] = useState<CodeSubTab>('changes');

  // Diff state (for Changes tab)
  const [diffResult, setDiffResult] = useState<GitDiffResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Selected file in Changes tab
  const [selectedDiffPath, setSelectedDiffPath] = useState<string | null>(null);

  // Open files state (for Files tab)
  const [openFiles, setOpenFiles] = useState<OpenFile[]>(loadOpenFiles);
  const [selectedFilePath, setSelectedFilePath] = useState<string | null>(null);
  const [fileContents, setFileContents] = useState<Map<string, string>>(new Map());
  const [loadingFile, setLoadingFile] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  // Comments - shared between both tabs
  const [comments, setComments] = useState<CodeReviewComment[]>(loadComments);

  // Commit modal state
  const [isCommitModalOpen, setIsCommitModalOpen] = useState(false);

  // Save comments to localStorage whenever they change
  useEffect(() => {
    saveComments(comments);
  }, [comments]);

  // Save open files to localStorage whenever they change
  useEffect(() => {
    saveOpenFiles(openFiles);
  }, [openFiles]);

  // Load diff when cwd changes or refresh is triggered
  const loadDiff = useCallback(async () => {
    if (!cwd || !client) {
      setDiffResult(null);
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      // Always load unstaged changes
      const result = await client.getGitDiff(cwd, false);
      setDiffResult(result);

      // Auto-select first file if none selected
      if (result.files.length > 0 && !selectedDiffPath && result.files[0]) {
        setSelectedDiffPath(result.files[0].path);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(message);
      setDiffResult(null);
    } finally {
      setIsLoading(false);
    }
  }, [cwd, client, selectedDiffPath]);

  // Load diff on mount and when dependencies change
  useEffect(() => {
    loadDiff();
  }, [loadDiff]);

  // Report git status changes to parent
  useEffect(() => {
    if (onGitStatusChange) {
      if (diffResult) {
        onGitStatusChange({
          hasUnstaged: diffResult.hasUnstaged,
          hasStaged: diffResult.hasStaged,
          fileCount: diffResult.files.length,
        });
      } else {
        onGitStatusChange(null);
      }
    }
  }, [diffResult, onGitStatusChange]);

  // Open a file in the Files tab
  const openFile = useCallback(async (path: string) => {
    if (!client) return;

    log('openFile', { path });

    // Check if already open
    const existing = openFiles.find(f => f.path === path);
    if (existing) {
      // Just select it
      setSelectedFilePath(path);
      setActiveSubTab('files');
      return;
    }

    // Check if file exists and get size
    try {
      const exists = await client.pathExists(path);
      if (!exists) {
        await alert({
          title: 'File Not Found',
          message: `The file "${path}" does not exist.`,
        });
        return;
      }

      const isDir = await client.isDirectory(path);
      if (isDir) {
        await alert({
          title: 'Cannot Open Directory',
          message: 'Please select a file, not a directory.',
        });
        return;
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      await alert({
        title: 'Error',
        message: `Failed to check file: ${message}`,
      });
      return;
    }

    // Read the file to check size and content
    setLoadingFile(path);
    setFileError(null);

    try {
      const content = await client.readFile(path);
      const size = new Blob([content]).size;

      // Check for large file
      if (size > LARGE_FILE_THRESHOLD) {
        const proceed = await confirm({
          title: 'Large File Warning',
          message: `This file is ${formatSize(size)}. Opening large files may affect performance. Continue?`,
          confirmText: 'Open Anyway',
          cancelText: 'Cancel',
          variant: 'warning',
        });

        if (!proceed) {
          setLoadingFile(null);
          return;
        }
      }

      // Check for binary content
      if (isBinaryContent(content)) {
        await alert({
          title: 'Binary File',
          message: 'This appears to be a binary file and cannot be displayed as text.',
        });
        setLoadingFile(null);
        return;
      }

      // Add to open files
      const newFile: OpenFile = { path, size };
      setOpenFiles(prev => [...prev, newFile]);
      setFileContents(prev => new Map(prev).set(path, content));
      setSelectedFilePath(path);
      setActiveSubTab('files');
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setFileError(message);
      await alert({
        title: 'Error Reading File',
        message,
      });
    } finally {
      setLoadingFile(null);
    }
  }, [client, openFiles, alert, confirm]);

  // Expose handle to parent
  useImperativeHandle(ref, () => ({
    openFile,
  }), [openFile]);

  // Close a file
  const closeFile = useCallback((path: string) => {
    setOpenFiles(prev => prev.filter(f => f.path !== path));
    setFileContents(prev => {
      const next = new Map(prev);
      next.delete(path);
      return next;
    });

    // If closing the selected file, select another
    if (selectedFilePath === path) {
      const remaining = openFiles.filter(f => f.path !== path);
      setSelectedFilePath(remaining.length > 0 ? remaining[0]!.path : null);
    }
  }, [openFiles, selectedFilePath]);

  // Get the selected diff file
  const selectedDiffFile = useMemo(() => {
    if (!diffResult || !selectedDiffPath) return null;
    return diffResult.files.find((f) => f.path === selectedDiffPath) || null;
  }, [diffResult, selectedDiffPath]);

  // Handle diff file selection
  const handleSelectDiffFile = useCallback((path: string) => {
    setSelectedDiffPath(path);
  }, []);

  // Handle open file selection - loads content if not cached
  const handleSelectOpenFile = useCallback(async (path: string) => {
    setSelectedFilePath(path);

    // If content is already cached, nothing more to do
    if (fileContents.has(path)) {
      return;
    }

    // Content not cached - need to load it
    if (!client) return;

    setLoadingFile(path);
    setFileError(null);

    try {
      const content = await client.readFile(path);

      // Check for binary content
      if (isBinaryContent(content)) {
        await alert({
          title: 'Binary File',
          message: 'This appears to be a binary file and cannot be displayed as text.',
        });
        // Remove from open files since we can't display it
        setOpenFiles(prev => prev.filter(f => f.path !== path));
        setSelectedFilePath(null);
        setLoadingFile(null);
        return;
      }

      setFileContents(prev => new Map(prev).set(path, content));
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setFileError(message);
      await alert({
        title: 'Error Reading File',
        message,
      });
      // Remove from open files since we can't read it
      setOpenFiles(prev => prev.filter(f => f.path !== path));
      setSelectedFilePath(null);
    } finally {
      setLoadingFile(null);
    }
  }, [client, fileContents, alert]);

  // Add a comment
  const handleAddComment = useCallback((comment: Omit<CodeReviewComment, 'id'>) => {
    const newComment: CodeReviewComment = {
      ...comment,
      id: generateId(),
    };
    setComments((prev) => [...prev, newComment]);
  }, []);

  // Edit an existing comment
  const handleEditComment = useCallback((commentId: string, newText: string) => {
    setComments((prev) =>
      prev.map((c) => (c.id === commentId ? { ...c, comment: newText } : c))
    );
  }, []);

  // Delete a comment
  const handleDeleteComment = useCallback((commentId: string) => {
    setComments((prev) => prev.filter((c) => c.id !== commentId));
  }, []);

  // Clear all comments
  const handleClearComments = useCallback(async () => {
    if (comments.length === 0) return;

    const confirmed = await confirm({
      title: 'Clear All Comments?',
      message: `This will remove ${comments.length} comment${comments.length > 1 ? 's' : ''}.`,
      confirmText: 'Clear',
      cancelText: 'Keep',
      variant: 'warning',
    });

    if (confirmed) {
      setComments([]);
    }
  }, [comments.length, confirm]);

  // Submit comments as a review
  const handleSubmit = useCallback(async () => {
    if (comments.length === 0) {
      await alert({
        title: 'No Comments',
        message: 'Add at least one comment before submitting.',
      });
      return;
    }

    if (onSubmitReview) {
      const review: CodeReview = {
        id: generateId(),
        comments: [...comments],
        created_at: new Date().toISOString(),
      };
      onSubmitReview(review);
    }

    // Clear comments after submission
    setComments([]);
  }, [comments, onSubmitReview, alert]);

  // Refresh diff
  const handleRefresh = useCallback(() => {
    // Clear selection if file no longer exists
    if (selectedDiffPath && diffResult) {
      const stillExists = diffResult.files.some((f) => f.path === selectedDiffPath);
      if (!stillExists) {
        setSelectedDiffPath(null);
      }
    }
    loadDiff();
  }, [loadDiff, selectedDiffPath, diffResult]);

  // Handle commit success - refresh the diff
  const handleCommitSuccess = useCallback((commitHash: string) => {
    log('Commit successful', { commitHash });
    // Refresh the diff to show updated state
    loadDiff();
  }, [loadDiff]);

  // Build a ReviewState for views
  const reviewState = useMemo(() => ({
    active: true, // Always active - selection always enabled
    review: {
      id: 'current',
      comments,
      created_at: new Date().toISOString(),
    },
  }), [comments]);

  // Get the content for selected open file
  const selectedFileContent = selectedFilePath ? fileContents.get(selectedFilePath) : undefined;

  // Render loading state (only for initial diff load)
  if (isLoading && !diffResult && activeSubTab === 'changes') {
    return (
      <div className="code-tab code-tab--loading">
        <div className="code-tab__spinner" />
        <span>Loading changes...</span>
      </div>
    );
  }

  // Render error state (only for diff errors)
  if (error && activeSubTab === 'changes') {
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

  const commentCount = comments.length;

  return (
    <div className="code-tab">
      {/* Header / toolbar */}
      <div className="code-tab__header">
        {/* Sub-tabs */}
        <div className="code-tab__subtabs">
          <button
            className={`code-tab__subtab ${activeSubTab === 'changes' ? 'code-tab__subtab--active' : ''}`}
            onClick={() => setActiveSubTab('changes')}
          >
            Changes
            {diffResult && diffResult.files.length > 0 && (
              <span className="code-tab__subtab-badge">
                {diffResult.files.length}
              </span>
            )}
          </button>
          <button
            className={`code-tab__subtab ${activeSubTab === 'files' ? 'code-tab__subtab--active' : ''}`}
            onClick={() => setActiveSubTab('files')}
          >
            Files
            {openFiles.length > 0 && (
              <span className="code-tab__subtab-badge">
                {openFiles.length}
              </span>
            )}
          </button>
        </div>

        {/* Actions */}
        <div className="code-tab__actions">
          {/* Refresh (only for changes tab) */}
          {activeSubTab === 'changes' && (
            <button
              className="code-tab__refresh"
              onClick={handleRefresh}
              disabled={isLoading}
              title="Refresh"
            >
              {isLoading ? '...' : '↻'}
            </button>
          )}

          {/* Commit button (only for changes tab with files) */}
          {activeSubTab === 'changes' && diffResult && diffResult.files.length > 0 && (
            <button
              className="code-tab__commit"
              onClick={() => setIsCommitModalOpen(true)}
              title="Commit changes"
            >
              Commit
            </button>
          )}

          {/* Clear comments */}
          {commentCount > 0 && (
            <button
              className="code-tab__clear"
              onClick={handleClearComments}
              title="Clear all comments"
            >
              ×
            </button>
          )}

          {/* Submit button - always visible */}
          <button
            className="code-tab__submit"
            onClick={handleSubmit}
            disabled={commentCount === 0}
            title={commentCount === 0 ? 'Add comments to submit' : `Submit ${commentCount} comment${commentCount > 1 ? 's' : ''}`}
          >
            Submit{commentCount > 0 ? ` (${commentCount})` : ''}
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="code-tab__content">
        {activeSubTab === 'changes' ? (
          <>
            {/* File list sidebar */}
            <div className="code-tab__sidebar">
              <FileList
                files={diffResult?.files || []}
                selectedPath={selectedDiffPath}
                onSelectFile={handleSelectDiffFile}
              />
            </div>

            {/* Diff view */}
            <div className="code-tab__main">
              {selectedDiffFile ? (
                <DiffView
                  file={selectedDiffFile}
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
                    <p>No unstaged changes</p>
                  )}
                </div>
              )}
            </div>
          </>
        ) : (
          <>
            {/* Open files sidebar */}
            <div className="code-tab__sidebar">
              <OpenFilesList
                files={openFiles}
                selectedPath={selectedFilePath}
                onSelectFile={handleSelectOpenFile}
                onCloseFile={closeFile}
              />
            </div>

            {/* File content view */}
            <div className="code-tab__main">
              {loadingFile ? (
                <div className="code-tab__loading-file">
                  <div className="code-tab__spinner" />
                  <span>Loading file...</span>
                </div>
              ) : selectedFilePath && selectedFileContent !== undefined ? (
                <FileContentView
                  filePath={selectedFilePath}
                  content={selectedFileContent}
                  reviewState={reviewState}
                  onAddComment={handleAddComment}
                  onEditComment={handleEditComment}
                  onDeleteComment={handleDeleteComment}
                />
              ) : (
                <div className="code-tab__no-selection">
                  <p>Select a file from the browser</p>
                  <p className="code-tab__hint">
                    Click a file in the file browser (right panel) to open it here
                  </p>
                </div>
              )}
            </div>
          </>
        )}
      </div>

      {/* Commit Modal */}
      {diffResult && (
        <CommitModal
          isOpen={isCommitModalOpen}
          onClose={() => setIsCommitModalOpen(false)}
          gitRoot={diffResult.gitRoot}
          changedFiles={diffResult.files}
          client={client}
          onCommitSuccess={handleCommitSuccess}
          onRequestAIMessage={onRequestAICommitMessage}
        />
      )}
    </div>
  );
}));

export default CodeTab;

// Re-export types
export type { CodeReview, CodeReviewComment } from './types';
