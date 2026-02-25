/**
 * CommitModal - Modal for staging and committing git changes
 *
 * Features:
 * - Shows list of changed files with checkboxes for staging
 * - Auto-generate commit message option (simple or AI-powered)
 * - Editable commit message textarea
 * - Stage selected files and commit in one action
 */

import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { FileStateServiceClient, DiffFile } from '../../../../generated/balloons-client';
import './CommitModal.css';

export interface CommitModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close */
  onClose: () => void;

  /** Git root directory */
  gitRoot: string;

  /** List of changed files from the diff */
  changedFiles: DiffFile[];

  /** FileStateService client for git operations */
  client: FileStateServiceClient;

  /** Callback when commit is successful */
  onCommitSuccess?: (commitHash: string) => void;

  /** Optional: callback to generate AI commit message using the staged diff */
  onRequestAIMessage?: (gitRoot: string, stagedDiff: string) => Promise<string>;
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
 * Modal for staging files and creating commits.
 */
export const CommitModal = memo(function CommitModal({
  isOpen,
  onClose,
  gitRoot,
  changedFiles,
  client,
  onCommitSuccess,
  onRequestAIMessage,
}: CommitModalProps) {
  // Selected files for staging (by path)
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set());

  // Commit message
  const [message, setMessage] = useState('');

  // Auto-generate option
  const [autoGenerate, setAutoGenerate] = useState(true);

  // Loading states
  const [isGenerating, setIsGenerating] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);

  // Error state
  const [error, setError] = useState<string | null>(null);

  // Ref for message textarea
  const messageRef = useRef<HTMLTextAreaElement>(null);

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      // Select all files by default
      setSelectedFiles(new Set(changedFiles.map(f => f.path)));
      setMessage('');
      setError(null);
      setIsGenerating(false);
      setIsCommitting(false);
    }
  }, [isOpen, changedFiles]);

  // Generate commit message when selection changes (if auto-generate is on)
  useEffect(() => {
    if (!isOpen || !autoGenerate || selectedFiles.size === 0) return;

    const generateMessage = async () => {
      setIsGenerating(true);
      setError(null);

      try {
        // Try AI message first if available
        if (onRequestAIMessage) {
          // Get the staged diff for the selected files
          // First, stage the selected files
          const selectedPaths = Array.from(selectedFiles);
          await client.stageFiles(gitRoot, selectedPaths);

          // Get the staged diff
          const stagedDiffResult = await client.getStagedDiff(gitRoot);

          // Build a simple diff string from the staged files
          let diffText = '';
          for (const file of stagedDiffResult.files) {
            diffText += `\n--- a/${file.path}\n+++ b/${file.path}\n`;
            for (const hunk of file.hunks) {
              diffText += hunk.header + '\n';
              for (const change of hunk.changes) {
                const prefix = change.type === 'insert' ? '+' : change.type === 'delete' ? '-' : ' ';
                diffText += prefix + change.content + '\n';
              }
            }
          }

          if (diffText) {
            const aiMessage = await onRequestAIMessage(gitRoot, diffText);
            if (aiMessage) {
              setMessage(aiMessage);
              setIsGenerating(false);
              return;
            }
          }
        }

        // Fall back to simple auto-generated message
        const simpleMessage = await client.generateCommitMessage(gitRoot);
        setMessage(simpleMessage || '');
      } catch (e) {
        console.error('Failed to generate commit message:', e);
        // Don't show error for message generation - just leave empty
      } finally {
        setIsGenerating(false);
      }
    };

    // Debounce the generation
    const timer = setTimeout(generateMessage, 300);
    return () => clearTimeout(timer);
  }, [isOpen, autoGenerate, selectedFiles, gitRoot, client, onRequestAIMessage]);

  // Toggle file selection
  const toggleFile = useCallback((path: string) => {
    setSelectedFiles(prev => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  // Select all files
  const selectAll = useCallback(() => {
    setSelectedFiles(new Set(changedFiles.map(f => f.path)));
  }, [changedFiles]);

  // Deselect all files
  const deselectAll = useCallback(() => {
    setSelectedFiles(new Set());
  }, []);

  // Handle commit
  const handleCommit = useCallback(async () => {
    if (selectedFiles.size === 0) {
      setError('No files selected to commit');
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
      // Stage selected files
      const selectedPaths = Array.from(selectedFiles);
      const stageResult = await client.stageFiles(gitRoot, selectedPaths);

      if (!stageResult.success) {
        setError(stageResult.message);
        setIsCommitting(false);
        return;
      }

      // Create commit
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
  }, [selectedFiles, message, gitRoot, client, onCommitSuccess, onClose]);

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

  const allSelected = selectedFiles.size === changedFiles.length;
  const noneSelected = selectedFiles.size === 0;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Commit Changes"
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

        {/* File selection */}
        <div className="commit-modal__section">
          <div className="commit-modal__section-header">
            <span className="commit-modal__section-title">
              Files to commit ({selectedFiles.size}/{changedFiles.length})
            </span>
            <div className="commit-modal__select-actions">
              <button
                type="button"
                className="commit-modal__select-btn"
                onClick={selectAll}
                disabled={allSelected}
              >
                All
              </button>
              <button
                type="button"
                className="commit-modal__select-btn"
                onClick={deselectAll}
                disabled={noneSelected}
              >
                None
              </button>
            </div>
          </div>

          <div className="commit-modal__file-list">
            {changedFiles.map((file) => {
              const config = STATUS_CONFIG[file.status] || { icon: '?', color: '#888', label: file.status };
              const isSelected = selectedFiles.has(file.path);

              return (
                <label
                  key={file.path}
                  className={`commit-modal__file ${isSelected ? 'commit-modal__file--selected' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleFile(file.path)}
                    className="commit-modal__checkbox"
                  />
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
                </label>
              );
            })}
          </div>
        </div>

        {/* Commit message */}
        <div className="commit-modal__section">
          <div className="commit-modal__section-header">
            <span className="commit-modal__section-title">Commit message</span>
            {isGenerating ? (
              <div className="commit-modal__generating">
                <div className="commit-modal__spinner" />
                <span>Generating with AI...</span>
              </div>
            ) : (
              <label className="commit-modal__auto-generate">
                <input
                  type="checkbox"
                  checked={autoGenerate}
                  onChange={(e) => setAutoGenerate(e.target.checked)}
                />
                <span>Auto-generate</span>
              </label>
            )}
          </div>

          <textarea
            ref={messageRef}
            className="commit-modal__message"
            placeholder={isGenerating ? 'Generating message...' : 'Enter commit message...'}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isCommitting || isGenerating}
            rows={4}
          />
          <div className="commit-modal__hint">
            Press {navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+Enter to commit
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
          disabled={isCommitting || noneSelected || !message.trim()}
        >
          {isCommitting ? 'Committing...' : `Commit ${selectedFiles.size} file${selectedFiles.size !== 1 ? 's' : ''}`}
        </button>
      </ModalFooter>
    </Modal>
  );
});

export default CommitModal;
