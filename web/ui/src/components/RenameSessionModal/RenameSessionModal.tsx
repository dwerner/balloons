/**
 * RenameSessionModal - Modal for renaming a session and navigating the fork tree
 *
 * Features:
 * - Title input field with current session name pre-filled
 * - Save button to confirm rename
 * - Full fork tree display (parents, siblings, children)
 * - Click any session in tree to navigate to it
 * - Cancel button to dismiss without changes
 * - Dismiss on Escape or backdrop click
 * - Calls client.sessions.setSessionTitle() on submit
 */

import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { SessionManagerServiceClient, SessionDataServiceClient } from '../../../../generated/client';
import type { ForkTreeNode } from '../../../../generated/types';
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

  /** Called when user wants to navigate to another session */
  onNavigateToSession?: (sessionId: string) => void;
}

/**
 * Recursive component to render a fork tree node
 */
interface ForkTreeNodeViewProps {
  node: ForkTreeNode;
  depth: number;
  onNavigate?: (sessionId: string) => void;
}

const ForkTreeNodeView = memo(function ForkTreeNodeView({
  node,
  depth,
  onNavigate,
}: ForkTreeNodeViewProps) {
  const hasChildren = node.children && node.children.length > 0;
  const hasWatchTargets = node.watchTargets && node.watchTargets.length > 0;
  const hasWatchers = node.watchedBy && node.watchedBy.length > 0;
  const hasExpandableContent = hasChildren || hasWatchTargets || hasWatchers;
  const [isExpanded, setIsExpanded] = useState(depth < 3); // Auto-expand first 3 levels

  const handleClick = useCallback(() => {
    if (!node.isCurrent && onNavigate) {
      onNavigate(node.sessionId);
    }
  }, [node.sessionId, node.isCurrent, onNavigate]);

  const toggleExpand = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsExpanded(prev => !prev);
  }, []);

  return (
    <div className="fork-tree-node">
      <div
        className={`fork-tree-node__content ${node.isCurrent ? 'fork-tree-node__content--current' : ''} ${node.status === 'merged' ? 'fork-tree-node__content--merged' : ''} ${node.status === 'abandoned' ? 'fork-tree-node__content--abandoned' : ''}`}
        onClick={handleClick}
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        title={node.isCurrent ? 'Current session' : `Navigate to ${node.name}`}
      >
        {hasExpandableContent ? (
          <button
            type="button"
            className="fork-tree-node__toggle"
            onClick={toggleExpand}
            aria-label={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="fork-tree-node__spacer" />
        )}
        <span className="fork-tree-node__icon">
          {node.isCurrent ? '●' : node.status === 'merged' ? '✓' : '⑂'}
        </span>
        <span className="fork-tree-node__name">{node.name}</span>
        <span className="fork-tree-node__id">{node.sessionId.slice(0, 8)}</span>
        {node.watchTargets && node.watchTargets.length > 0 && (
          <span className="fork-tree-node__watching" title={`Watching ${node.watchTargets.length} session(s)`}>
            👁→{node.watchTargets.length}
          </span>
        )}
        {node.watchedBy && node.watchedBy.length > 0 && (
          <span className="fork-tree-node__watched-by" title={`Watched by ${node.watchedBy.length} session(s)`}>
            ←👁{node.watchedBy.length}
          </span>
        )}
        {node.status !== 'active' && (
          <span className="fork-tree-node__status">({node.status})</span>
        )}
      </div>
      {/* Show children, watch targets, and watchers when expanded */}
      {isExpanded && hasExpandableContent && (
        <div className="fork-tree-node__children">
          {/* Render child nodes */}
          {node.children?.map(child => (
            <ForkTreeNodeView
              key={child.sessionId}
              node={child}
              depth={depth + 1}
              onNavigate={onNavigate}
            />
          ))}
          {/* Render watch targets as navigable items */}
          {node.watchTargets && node.watchTargets.length > 0 && (
            <div className="fork-tree-node__watch-section">
              {node.watchTargets.map(targetId => (
                <div
                  key={`target-${targetId}`}
                  className="fork-tree-node__watch-target"
                  onClick={() => onNavigate?.(targetId)}
                  style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
                  title={`Navigate to watched session ${targetId.slice(0, 8)}`}
                >
                  <span className="fork-tree-node__spacer" />
                  <span className="fork-tree-node__icon fork-tree-node__icon--watching">👁→</span>
                  <span className="fork-tree-node__id">{targetId.slice(0, 8)}</span>
                  <span className="fork-tree-node__label fork-tree-node__label--muted">(watching)</span>
                </div>
              ))}
            </div>
          )}
          {/* Render watchers (who is watching this session) */}
          {node.watchedBy && node.watchedBy.length > 0 && (
            <div className="fork-tree-node__watch-section">
              {node.watchedBy.map(watcherId => (
                <div
                  key={`watcher-${watcherId}`}
                  className="fork-tree-node__watch-target fork-tree-node__watch-target--watcher"
                  onClick={() => onNavigate?.(watcherId)}
                  style={{ paddingLeft: `${(depth + 1) * 16 + 8}px` }}
                  title={`Navigate to watcher session ${watcherId.slice(0, 8)}`}
                >
                  <span className="fork-tree-node__spacer" />
                  <span className="fork-tree-node__icon fork-tree-node__icon--watching">←👁</span>
                  <span className="fork-tree-node__id">{watcherId.slice(0, 8)}</span>
                  <span className="fork-tree-node__label fork-tree-node__label--muted">(watcher)</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

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

  // Fork tree state
  const [forkTree, setForkTree] = useState<ForkTreeNode | null>(null);
  const [isLoadingTree, setIsLoadingTree] = useState(false);

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

  // Load fork tree when modal opens
  useEffect(() => {
    if (isOpen && sessionDataClient) {
      setIsLoadingTree(true);
      debugLog('Fetching fork tree', { sessionId });
      sessionDataClient.getSessionForkTree(sessionId)
        .then(tree => {
          debugLog('Got fork tree', { hasTree: !!tree, rootName: tree?.name });
          setForkTree(tree);
        })
        .catch(err => {
          debugLog('Failed to load fork tree', { error: String(err) });
          setForkTree(null);
        })
        .finally(() => {
          setIsLoadingTree(false);
        });
    } else if (!isOpen) {
      setForkTree(null);
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

  // Handle navigation to any session in the tree
  const handleNavigateToSession = useCallback((targetSessionId: string) => {
    if (onNavigateToSession) {
      onNavigateToSession(targetSessionId);
      onClose();
    }
  }, [onNavigateToSession, onClose]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Session"
      size="medium"
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

        {/* Fork tree section */}
        {(forkTree || isLoadingTree) && (
          <div className="rename-session-modal__fork-tree">
            <span className="rename-session-modal__label">Session Tree</span>
            {isLoadingTree ? (
              <div className="rename-session-modal__tree-loading">Loading...</div>
            ) : forkTree ? (
              <div className="rename-session-modal__tree-container">
                <ForkTreeNodeView
                  node={forkTree}
                  depth={0}
                  onNavigate={onNavigateToSession ? handleNavigateToSession : undefined}
                />
              </div>
            ) : null}
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
