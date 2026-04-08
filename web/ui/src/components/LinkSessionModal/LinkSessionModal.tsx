/**
 * LinkSessionModal - Modal for linking the current session to another session
 *
 * Features:
 * - Searchable list of available sessions
 * - Filters out the current session
 * - Optional summary/description field for the link
 * - Shows session metadata (name, message count, date)
 * - Calls linkSessions API on confirm
 */

import React, { useState, useCallback, useMemo, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { SessionManagerServiceClient, SessionDataServiceClient } from '../../../../generated/client';
import type { SessionInfo } from '../../../../generated/types';
import { createLogger } from '../../utils/debugLog';
import './LinkSessionModal.css';

const debugLog = createLogger('LinkSessionModal');

// Custom comparison function for memo - prevents re-renders when modal is open
// When modal is open, internal state manages the form, so we only need to re-render
// when isOpen changes from true to false (closing) or false to true (opening)
function arePropsEqual(prevProps: LinkSessionModalProps, nextProps: LinkSessionModalProps): boolean {
  // If modal is open in both prev and next, skip re-render
  // Internal state handles the form values during editing
  if (prevProps.isOpen && nextProps.isOpen) {
    return true;
  }
  // Otherwise use default shallow comparison for memo
  return false;
}

export interface LinkSessionModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close */
  onClose: () => void;

  /** Current session ID (will be excluded from list) */
  currentSessionId: string;

  /** Initial summary/description for the link */
  initialSummary?: string;

  /** Session manager client for linking */
  sessionClient: SessionManagerServiceClient;

  /** Session data client for fetching sessions */
  sessionDataClient: SessionDataServiceClient;

  /** Called when sessions are successfully linked */
  onLinked?: (targetSessionId: string, linkId: string) => void;
}

/**
 * Format a date string for display
 */
function formatDate(dateStr: string): string {
  try {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffDays === 0) {
      return 'Today';
    } else if (diffDays === 1) {
      return 'Yesterday';
    } else if (diffDays < 7) {
      return `${diffDays} days ago`;
    } else {
      return date.toLocaleDateString();
    }
  } catch {
    return dateStr;
  }
}

/**
 * Session item in the list
 */
interface SessionItemProps {
  session: SessionInfo;
  isSelected: boolean;
  onSelect: (id: string) => void;
}

const SessionItem = memo(function SessionItem({
  session,
  isSelected,
  onSelect,
}: SessionItemProps) {
  const handleClick = useCallback(() => {
    onSelect(session.id);
  }, [session.id, onSelect]);

  const displayName = session.forkName || session.title || session.id.slice(0, 8);
  const isConcluded = session.concluded;
  const isPinned = session.isPinned;

  return (
    <button
      type="button"
      className={`link-session-item ${isSelected ? 'link-session-item--selected' : ''} ${isConcluded ? 'link-session-item--concluded' : ''}`}
      onClick={handleClick}
    >
      <div className="link-session-item__main">
        <span className="link-session-item__icon">
          {isPinned ? '📌' : isConcluded ? '✓' : '💬'}
        </span>
        <span className="link-session-item__name">{displayName}</span>
        <span className="link-session-item__id">{session.id.slice(0, 8)}</span>
      </div>
      <div className="link-session-item__meta">
        <span className="link-session-item__count">{session.messageCount} turns</span>
        <span className="link-session-item__date">{formatDate(session.lastModified)}</span>
      </div>
    </button>
  );
});

/**
 * Modal for linking to another session
 */
export const LinkSessionModal = memo(function LinkSessionModal({
  isOpen,
  onClose,
  currentSessionId,
  initialSummary = '',
  sessionClient,
  sessionDataClient,
  onLinked,
}: LinkSessionModalProps) {
  // State
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [summary, setSummary] = useState(initialSummary);
  const [isLinking, setIsLinking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Refs
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Load sessions when modal opens
  useEffect(() => {
    if (isOpen) {
      setIsLoading(true);
      setError(null);
      setSearchQuery('');
      setSelectedSessionId(null);
      setSummary(initialSummary);

      debugLog('Loading sessions for link modal');
      sessionDataClient.getAllSessions()
        .then((allSessions) => {
          debugLog('Got sessions', { count: allSessions.length });
          setSessions(allSessions);
        })
        .catch((err) => {
          debugLog('Failed to load sessions', { error: String(err) });
          setError('Failed to load sessions');
        })
        .finally(() => {
          setIsLoading(false);
        });

      // Focus search input
      setTimeout(() => {
        searchInputRef.current?.focus();
      }, 50);
    }
  }, [isOpen, initialSummary, sessionDataClient]);

  // Filter sessions based on search query, excluding current session
  const filteredSessions = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return sessions
      .filter((s) => s.id !== currentSessionId)
      .filter((s) => {
        if (!query) return true;
        const name = (s.forkName || s.title || '').toLowerCase();
        const id = s.id.toLowerCase();
        return name.includes(query) || id.includes(query);
      })
      .sort((a, b) => {
        // Sort by: pinned first, then by last modified (most recent first)
        if (a.isPinned && !b.isPinned) return -1;
        if (!a.isPinned && b.isPinned) return 1;
        return new Date(b.lastModified).getTime() - new Date(a.lastModified).getTime();
      });
  }, [sessions, currentSessionId, searchQuery]);

  // Handle search input change
  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
  }, []);

  // Handle session selection
  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId((prev) => (prev === sessionId ? null : sessionId));
  }, []);

  // Handle summary change
  const handleSummaryChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setSummary(e.target.value);
  }, []);

  // Handle link action
  const handleLink = useCallback(async () => {
    if (!selectedSessionId) {
      setError('Please select a session to link');
      return;
    }

    setIsLinking(true);
    setError(null);

    try {
      debugLog('Linking sessions', {
        source: currentSessionId,
        target: selectedSessionId,
        summary: summary || undefined,
      });

      const result = await sessionClient.linkSessions(
        currentSessionId,
        selectedSessionId,
        summary || undefined
      );

      if (result.linkId) {
        debugLog('Sessions linked successfully', { linkId: result.linkId });
        onLinked?.(selectedSessionId, result.linkId);
        onClose();
      } else if (result.error) {
        setError(result.error);
      } else {
        setError('Failed to link sessions');
      }
    } catch (err) {
      debugLog('Link error', { error: String(err) });
      setError(err instanceof Error ? err.message : 'Failed to link sessions');
    } finally {
      setIsLinking(false);
    }
  }, [currentSessionId, selectedSessionId, summary, sessionClient, onLinked, onClose]);

  // Handle Enter key in search to select first result
  const handleSearchKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && filteredSessions.length > 0) {
      e.preventDefault();
      // Select first result if nothing selected, or link if already selected
      if (!selectedSessionId) {
        const firstSession = filteredSessions[0];
        if (firstSession) {
          setSelectedSessionId(firstSession.id);
        }
      } else {
        handleLink();
      }
    }
  }, [filteredSessions, selectedSessionId, handleLink]);

  const selectedSession = selectedSessionId
    ? sessions.find((s) => s.id === selectedSessionId)
    : null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Link to Session"
      size="medium"
      className="link-session-modal"
      ariaDescribedBy="link-session-description"
    >
      <div className="link-session-modal__content">
        {/* Error message */}
        {error && (
          <div className="link-session-modal__error" role="alert">
            {error}
          </div>
        )}

        {/* Search input */}
        <div className="link-session-modal__search">
          <input
            ref={searchInputRef}
            type="text"
            className="link-session-modal__search-input"
            placeholder="Search sessions by name..."
            value={searchQuery}
            onChange={handleSearchChange}
            onKeyDown={handleSearchKeyDown}
            disabled={isLoading || isLinking}
          />
        </div>

        {/* Session list */}
        <div className="link-session-modal__list">
          {isLoading ? (
            <div className="link-session-modal__loading">Loading sessions...</div>
          ) : filteredSessions.length === 0 ? (
            <div className="link-session-modal__empty">
              {searchQuery ? 'No sessions match your search' : 'No other sessions available'}
            </div>
          ) : (
            filteredSessions.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isSelected={session.id === selectedSessionId}
                onSelect={handleSelectSession}
              />
            ))
          )}
        </div>

        {/* Summary/description field */}
        <div className="link-session-modal__summary">
          <label className="link-session-modal__label">
            Link Description (optional)
            <textarea
              className="link-session-modal__summary-input"
              placeholder="Why are these sessions related?"
              value={summary}
              onChange={handleSummaryChange}
              disabled={isLinking}
              rows={2}
            />
          </label>
        </div>

        {/* Selected session preview */}
        {selectedSession && (
          <div className="link-session-modal__preview">
            <span className="link-session-modal__preview-label">Will link to:</span>
            <span className="link-session-modal__preview-name">
              {selectedSession.forkName || selectedSession.title || selectedSession.id.slice(0, 8)}
            </span>
          </div>
        )}
      </div>

      <ModalFooter>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onClose}
          disabled={isLinking}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleLink}
          disabled={isLinking || !selectedSessionId}
        >
          {isLinking ? 'Linking...' : 'Link Sessions'}
        </button>
      </ModalFooter>
    </Modal>
  );
}, arePropsEqual);

export default LinkSessionModal;
