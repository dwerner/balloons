/**
 * CommitModal - Modal for committing staged git changes
 *
 * This modal shows what's currently staged and allows creating a commit.
 * Files should be staged BEFORE opening this modal using the stage/unstage
 * controls in the FileList. This modal does NOT modify staging.
 *
 * Features:
 * - Shows list of staged files (read-only display)
 * - Auto-generate commit message option (AI-powered)
 * - Editable commit message textarea
 * - Commit the staged changes
 */

import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { FileStateServiceClient, DiffFile } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './CommitModal.css';

const log = createLogger('CommitModal');

// Custom comparison function for memo - prevents re-renders when modal is open
// When modal is open, internal state manages the form, so we only need to re-render
// when isOpen changes from true to false (closing) or false to true (opening)
function arePropsEqual(prevProps: CommitModalProps, nextProps: CommitModalProps): boolean {
  // If modal is open in both prev and next, skip re-render
  // Internal state handles the form values during editing
  if (prevProps.isOpen && nextProps.isOpen) {
    return true;
  }
  // Otherwise use default shallow comparison for memo
  return false;
}

/** Callback for streaming AI commit message generation */
export interface StreamingMessageCallbacks {
  onDelta: (delta: string) => void;
  onDone: (result: string) => void;
  onError: (error: string) => void;
}

export interface CommitModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close */
  onClose: () => void;

  /** Git root directory */
  gitRoot: string;

  /** List of files that are already staged */
  stagedFiles: DiffFile[];

  /** FileStateService client for git operations */
  client: FileStateServiceClient;

  /** Callback when commit is successful */
  onCommitSuccess?: (commitHash: string) => void;

  /** Optional: callback to start AI commit message generation with streaming */
  onStartAIMessage?: (
    gitRoot: string,
    stagedDiff: string,
    callbacks: StreamingMessageCallbacks
  ) => (() => void); // Returns cleanup function
}

// Status icons and colors
const STATUS_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  added: { icon: '+', color: '#4ade80', label: 'Added' },
  modified: { icon: 'M', color: '#facc15', label: 'Modified' },
  deleted: { icon: '-', color: '#f87171', label: 'Deleted' },
  renamed: { icon: 'R', color: '#c084fc', label: 'Renamed' },
  copied: { icon: 'C', color: '#60a5fa', label: 'Copied' },
};

/**
 * Modal for committing staged changes.
 */
export const CommitModal = memo(function CommitModal({
  isOpen,
  onClose,
  gitRoot,
  stagedFiles,
  client,
  onCommitSuccess,
  onStartAIMessage,
}: CommitModalProps) {
  // Commit message
  const [message, setMessage] = useState('');

  // Auto-generate option
  const [autoGenerate, setAutoGenerate] = useState(true);

  // Loading states
  const [isGenerating, setIsGenerating] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);

  // Timer for generation duration
  const [generationTime, setGenerationTime] = useState(0);

  // Error state
  const [error, setError] = useState<string | null>(null);

  // Ref for message textarea
  const messageRef = useRef<HTMLTextAreaElement>(null);

  // Track if we've generated a message for these staged files
  const lastGeneratedForRef = useRef<string>('');
  // Track if generation is in progress
  const generationInProgressRef = useRef<boolean>(false);
  // Cleanup function for current generation
  const cleanupRef = useRef<(() => void) | null>(null);
  // Timer interval ref
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Create a stable key for the staged files
  const stagedFilesKey = stagedFiles.map(f => f.path).sort().join('\n');

  // Helper to stop timer
  const stopTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Helper to start timer
  const startTimer = useCallback(() => {
    stopTimer();
    setGenerationTime(0);
    timerRef.current = setInterval(() => {
      setGenerationTime(t => t + 0.1);
    }, 100);
  }, [stopTimer]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopTimer();
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
    };
  }, [stopTimer]);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setMessage('');
      setError(null);
      setIsGenerating(false);
      setIsCommitting(false);
      setGenerationTime(0);
      lastGeneratedForRef.current = '';
      generationInProgressRef.current = false;
      stopTimer();
      if (cleanupRef.current) {
        cleanupRef.current();
        cleanupRef.current = null;
      }
    }
  }, [isOpen, stopTimer]);

  // Start generation - used by effect and manual button
  const startGeneration = useCallback(() => {
    if (generationInProgressRef.current || !onStartAIMessage || stagedFiles.length === 0) return;

    // Build a diff string from the staged files
    let diffText = '';
    for (const file of stagedFiles) {
      diffText += `\n--- a/${file.path}\n+++ b/${file.path}\n`;
      for (const hunk of file.hunks) {
        diffText += hunk.header + '\n';
        for (const change of hunk.changes) {
          const prefix = change.type === 'insert' ? '+' : change.type === 'delete' ? '-' : ' ';
          diffText += prefix + change.content + '\n';
        }
      }
    }

    if (!diffText) return;

    generationInProgressRef.current = true;
    setIsGenerating(true);
    setError(null);
    setMessage(''); // Clear to show streaming
    startTimer();

    log('startGeneration', { diffTextLength: diffText.length });

    // Start streaming with callbacks
    const cleanup = onStartAIMessage(gitRoot, diffText, {
      onDelta: (delta) => {
        setMessage(prev => prev + delta);
      },
      onDone: (result) => {
        log('Generation done', { resultLength: result.length });
        setMessage(result);
        setIsGenerating(false);
        generationInProgressRef.current = false;
        lastGeneratedForRef.current = stagedFilesKey;
        stopTimer();
        cleanupRef.current = null;
      },
      onError: (error) => {
        log('Generation error', { error });
        console.error('Commit message generation error:', error);
        setIsGenerating(false);
        generationInProgressRef.current = false;
        stopTimer();
        cleanupRef.current = null;
        // Don't show error - just leave message empty or with partial content
      },
    });

    cleanupRef.current = cleanup;
  }, [onStartAIMessage, stagedFiles, gitRoot, stagedFilesKey, startTimer, stopTimer]);

  // Generate commit message when modal opens with staged files (if auto-generate is on)
  useEffect(() => {
    if (!isOpen || !autoGenerate || stagedFiles.length === 0) return;

    // Skip if we already generated for these staged files
    if (lastGeneratedForRef.current === stagedFilesKey) {
      log('Skipping generation - already generated for these files');
      return;
    }

    // Skip if a generation is already in progress
    if (generationInProgressRef.current) {
      log('Skipping generation - already in progress');
      return;
    }

    // Small delay to avoid generating while modal is still animating
    const timer = setTimeout(startGeneration, 200);
    return () => clearTimeout(timer);
  }, [isOpen, autoGenerate, stagedFilesKey, stagedFiles, startGeneration]);

  // Handle commit
  const handleCommit = useCallback(async () => {
    if (stagedFiles.length === 0) {
      setError('No staged files to commit');
      return;
    }

    if (!message.trim()) {
      setError('Commit message is required');
      messageRef.current?.focus();
      return;
    }

    setIsCommitting(true);
    setError(null);

    try {
      // Create commit (files are already staged)
      const commitResult = await client.gitCommit(gitRoot, message.trim());

      if (!commitResult.success) {
        setError(commitResult.message);
        setIsCommitting(false);
        return;
      }

      // Success!
      if (onCommitSuccess && commitResult.path) {
        onCommitSuccess(commitResult.path);
      }

      onClose();
    } catch (e) {
      const errorMsg = e instanceof Error ? e.message : String(e);
      setError(`Commit failed: ${errorMsg}`);
    } finally {
      setIsCommitting(false);
    }
  }, [stagedFiles.length, message, gitRoot, client, onCommitSuccess, onClose]);

  // Handle Enter key in message (Cmd/Ctrl+Enter to commit)
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleCommit();
      }
    },
    [handleCommit]
  );

  // Manually trigger AI generation - just calls startGeneration
  const handleGenerateMessage = useCallback(() => {
    // Clear last generated so we regenerate
    lastGeneratedForRef.current = '';
    startGeneration();
  }, [startGeneration]);

  const noStagedFiles = stagedFiles.length === 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Commit Staged Changes"
      size="medium"
      className="commit-modal"
      ariaDescribedBy="commit-modal-description"
    >
      <div className="commit-modal__content">
        {/* Error message */}
        {error && (
          <div className="commit-modal__error" role="alert">
            {error}
          </div>
        )}

        {/* Staged files display (read-only) */}
        <div className="commit-modal__section">
          <div className="commit-modal__section-header">
            <span className="commit-modal__section-title">
              Staged files ({stagedFiles.length})
            </span>
          </div>

          {noStagedFiles ? (
            <div className="commit-modal__empty">
              <p>No files staged for commit.</p>
              <p className="commit-modal__empty-hint">
                Use the + button next to files in the Changes view to stage them.
              </p>
            </div>
          ) : (
            <div className="commit-modal__file-list">
              {stagedFiles.map((file) => {
                const config = STATUS_CONFIG[file.status] || { icon: '?', color: '#888', label: file.status };

                return (
                  <div
                    key={file.path}
                    className="commit-modal__file commit-modal__file--staged"
                  >
                    <span
                      className="commit-modal__file-status"
                      style={{ color: config.color }}
                      title={config.label}
                    >
                      {config.icon}
                    </span>
                    <span className="commit-modal__file-path" title={file.path}>
                      {file.path}
                    </span>
                    <span className="commit-modal__file-stats">
                      {file.additions > 0 && (
                        <span className="commit-modal__additions">+{file.additions}</span>
                      )}
                      {file.deletions > 0 && (
                        <span className="commit-modal__deletions">-{file.deletions}</span>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Commit message */}
        <div className="commit-modal__section">
          <div className="commit-modal__section-header">
            <span className="commit-modal__section-title">Commit message</span>
            {isGenerating ? (
              <div className="commit-modal__generating">
                <div className="commit-modal__spinner" />
                <span>Generating... {generationTime.toFixed(1)}s</span>
              </div>
            ) : (
              <div className="commit-modal__message-actions">
                {onStartAIMessage && (
                  <button
                    type="button"
                    className="commit-modal__generate-btn"
                    onClick={handleGenerateMessage}
                    disabled={noStagedFiles || isCommitting}
                  >
                    Generate
                  </button>
                )}
                <label className="commit-modal__auto-generate">
                  <input
                    type="checkbox"
                    checked={autoGenerate}
                    onChange={(e) => setAutoGenerate(e.target.checked)}
                  />
                  <span>Auto</span>
                </label>
              </div>
            )}
          </div>

          <textarea
            ref={messageRef}
            className={`commit-modal__message ${isGenerating ? 'commit-modal__message--streaming' : ''}`}
            placeholder={isGenerating ? '' : 'Enter commit message...'}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isCommitting || noStagedFiles}
            readOnly={isGenerating}
            rows={4}
          />
          <div className="commit-modal__hint">
            {isGenerating
              ? 'Streaming commit message from AI...'
              : `Press ${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+Enter to commit`
            }
          </div>
        </div>
      </div>

      <ModalFooter>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onClose}
          disabled={isCommitting}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-success"
          onClick={handleCommit}
          disabled={isCommitting || noStagedFiles || !message.trim()}
        >
          {isCommitting ? 'Committing...' : `Commit ${stagedFiles.length} file${stagedFiles.length !== 1 ? 's' : ''}`}
        </button>
      </ModalFooter>
    </Modal>
  );
}, arePropsEqual);

export default CommitModal;
