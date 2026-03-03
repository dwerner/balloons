/**
 * RenameSessionModal - Modal for renaming a session and navigating to parents
 *
 * Features:
 * - Title input field with current session name pre-filled
 * - Save button to confirm rename
 * - Parent session chain display (for forked sessions)
 * - Click parent to navigate to that session
 * - Cancel button to dismiss without changes
 * - Dismiss on Escape or backdrop click
 * - Calls client.sessions.setSessionTitle() on submit
 */

import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { SessionManagerServiceClient, SessionDataServiceClient } from '../../../../generated/client';
import type { SessionInfo } from '../../../../generated/types';
import { createLogger } from '../../utils/debugLog';
import './RenameSessionModal.css';

const debugLog = createLogger('RenameSessionModal');

export interface RenameSessionModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close (cancel or after submit) */
  onClose: () => void;

  /** The session ID to rename */
  sessionId: string;

  /** The current session title (pre-filled in input) */
  currentTitle: string;

  /** Session manager client for API calls */
  client: SessionManagerServiceClient;

  /** Session data client for fetching parent chain */
  sessionDataClient?: SessionDataServiceClient;

  /** Called when session is renamed successfully */
  onRenamed?: (newTitle: string) => void;

  /** Called when user wants to navigate to a parent session */
  onNavigateToSession?: (sessionId: string) => void;
}

/**
 * Get display name for a session
 */
function getSessionDisplayName(session: SessionInfo): string {
  return session.forkName || session.title || `Session ${session.id.slice(0, 8)}`;
}

/**
 * Modal for renaming a session.
 */
export const RenameSessionModal = memo(function RenameSessionModal({
  isOpen,
  onClose,
  sessionId,
  currentTitle,
  client,
  sessionDataClient,
  onRenamed,
  onNavigateToSession,
}: RenameSessionModalProps) {
  // Form state
  const [title, setTitle] = useState(currentTitle);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Parent chain state
  const [parentChain, setParentChain] = useState<SessionInfo[]>([]);
  const [isLoadingParents, setIsLoadingParents] = useState(false);

  // Ref for title input to focus on mount
  const titleInputRef = useRef<HTMLInputElement>(null);

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setTitle(currentTitle);
      setError(null);
      setIsSubmitting(false);
      // Focus title input and select all text after a short delay
      setTimeout(() => {
        titleInputRef.current?.focus();
        titleInputRef.current?.select();
      }, 50);
    }
  }, [isOpen, currentTitle]);

  // Load parent chain when modal opens
  useEffect(() => {
    debugLog('Parent chain effect triggered', { isOpen, sessionId, hasClient: !!sessionDataClient });
    if (isOpen && sessionDataClient) {
      setIsLoadingParents(true);
      debugLog('Fetching parent chain', { sessionId });
      sessionDataClient.getSessionParentChain(sessionId)
        .then(parents => {
          debugLog('Got parent chain', { count: parents.length, parents: parents.map(p => ({ id: p.id.slice(0, 8), name: p.forkName || p.title })) });
          setParentChain(parents);
        })
        .catch(err => {
          debugLog('Failed to load parent chain', { error: String(err) });
          setParentChain([]);
        })
        .finally(() => {
          setIsLoadingParents(false);
        });
    } else if (!isOpen) {
      setParentChain([]);
    }
  }, [isOpen, sessionId, sessionDataClient]);

  // Submit handler
  const handleSubmit = useCallback(async () => {
    // Validate title
    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      setError('Title is required');
      titleInputRef.current?.focus();
      return;
    }

    // Skip if title hasn't changed
    if (trimmedTitle === currentTitle) {
      onClose();
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const success = await client.setSessionTitle(sessionId, trimmedTitle);
      if (success) {
        onRenamed?.(trimmedTitle);
        onClose();
      } else {
        setError('Failed to rename session');
      }
    } catch (err) {
      console.error('Failed to rename session:', err);
      setError(err instanceof Error ? err.message : 'Failed to rename session');
    } finally {
      setIsSubmitting(false);
    }
  }, [title, currentTitle, sessionId, client, onRenamed, onClose]);

  // Handle Enter key in title input
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  // Handle parent session click
  const handleParentClick = useCallback((parentId: string) => {
    if (onNavigateToSession) {
      onNavigateToSession(parentId);
      onClose();
    }
  }, [onNavigateToSession, onClose]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Session"
      size="small"
      className="rename-session-modal"
      ariaDescribedBy="rename-session-description"
    >
      <div className="rename-session-modal__content">
        {/* Error message */}
        {error && (
          <div className="rename-session-modal__error" role="alert">
            {error}
          </div>
        )}

        {/* Form fields */}
        <div className="rename-session-modal__form">
          {/* Title input */}
          <label className="rename-session-modal__field">
            <span className="rename-session-modal__label">Session Title</span>
            <input
              ref={titleInputRef}
              type="text"
              className="rename-session-modal__input"
              placeholder="Enter session title..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isSubmitting}
              autoComplete="off"
            />
          </label>
        </div>

        {/* Parent chain section */}
        {(parentChain.length > 0 || isLoadingParents) && (
          <div className="rename-session-modal__parents">
            <span className="rename-session-modal__label">Parent Sessions</span>
            {isLoadingParents ? (
              <div className="rename-session-modal__parents-loading">Loading...</div>
            ) : (
              <div className="rename-session-modal__parents-list">
                {parentChain.map((parent, index) => (
                  <button
                    key={parent.id}
                    type="button"
                    className="rename-session-modal__parent-item"
                    onClick={() => handleParentClick(parent.id)}
                    disabled={!onNavigateToSession}
                    title={`Navigate to ${getSessionDisplayName(parent)}`}
                  >
                    <span className="rename-session-modal__parent-depth">
                      {'↑'.repeat(index + 1)}
                    </span>
                    <span className="rename-session-modal__parent-name">
                      {getSessionDisplayName(parent)}
                    </span>
                    <span className="rename-session-modal__parent-id">
                      {parent.id.slice(0, 8)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <ModalFooter>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onClose}
          disabled={isSubmitting}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleSubmit}
          disabled={isSubmitting || !title.trim()}
        >
          {isSubmitting ? 'Saving...' : 'Save'}
        </button>
      </ModalFooter>
    </Modal>
  );
});

export default RenameSessionModal;
