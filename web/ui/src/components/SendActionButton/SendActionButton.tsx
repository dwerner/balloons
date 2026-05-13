import React, { useState, useRef, useCallback, useEffect } from 'react';
import { useLongPress } from '../../hooks';
import './SendActionButton.css';

export type SendAction = 'send' | 'btw' | 'fork' | 'conclude' | 'link' | 'merge' | 'reopen';

export interface SendActionButtonProps {
  /** Currently selected action */
  action: SendAction;
  /** Callback when action changes */
  onActionChange: (action: SendAction) => void;
  /** Callback when the button is clicked (executes current action) */
  onExecute: () => void;
  /** Whether the button is disabled */
  disabled?: boolean;
  /** Whether merge is available (only in forked sessions) */
  canMerge?: boolean;
  /** Whether session is currently streaming (affects available actions) */
  isStreaming?: boolean;
  /** Whether session is concluded (only reopen is available) */
  isConcluded?: boolean;
}

const ACTION_LABELS: Record<SendAction, string> = {
  send: 'Send',
  btw: 'BTW',
  fork: 'Fork',
  conclude: 'Conclude',
  link: 'Link',
  merge: 'Merge',
  reopen: 'Reopen',
};

const ACTION_DESCRIPTIONS: Record<SendAction, string> = {
  send: 'Send message to LLM',
  btw: 'Side comment (don\'t change course)',
  fork: 'Create new session from here',
  conclude: 'Mark session as concluded',
  link: 'Link to another session',
  merge: 'Merge back to parent session',
  reopen: 'Reopen this concluded session',
};

/**
 * SendActionButton - A send button with dropdown for multiple actions
 *
 * Desktop: Click button area to execute, click chevron for dropdown
 * Mobile: Long press to show dropdown, tap to execute
 */
export function SendActionButton({
  action,
  onActionChange,
  onExecute,
  disabled = false,
  canMerge = false,
  isStreaming = false,
  isConcluded = false,
}: SendActionButtonProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  // Close dropdown on escape
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsOpen(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const handleMainClick = useCallback(() => {
    if (disabled) return;
    onExecute();
  }, [disabled, onExecute]);

  const handleChevronClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (disabled) return;
    setIsOpen(prev => !prev);
  }, [disabled]);

  const handleSelectAction = useCallback((newAction: SendAction) => {
    onActionChange(newAction);
    setIsOpen(false);
  }, [onActionChange]);

  // Long press handler for mobile
  const longPressHandlers = useLongPress({
    onLongPress: () => {
      if (!disabled) {
        setIsOpen(true);
      }
    },
    onClick: handleMainClick,
    delay: 400,
  });

  // Available actions based on context
  let filteredActions: SendAction[];

  if (isConcluded) {
    // Concluded session: only reopen is available
    filteredActions = ['reopen'];
  } else if (isStreaming) {
    // Streaming: send and BTW are steering-style actions
    filteredActions = ['send', 'btw'];
  } else {
    // Normal session
    filteredActions = ['send', 'btw', 'fork', 'conclude', 'link'];
    if (canMerge) {
      filteredActions.push('merge');
    }
  }

  // Determine the effective action to display
  const effectiveAction = isConcluded ? 'reopen' : action;

  // For concluded sessions, show only reopen button (no dropdown)
  if (isConcluded) {
    return (
      <div className="send-action-button" ref={containerRef} data-action="reopen">
        <div className="send-action-button__main send-action-button__main--single">
          <button
            type="button"
            className="send-action-button__action"
            disabled={disabled}
            onClick={handleMainClick}
            aria-label={ACTION_DESCRIPTIONS.reopen}
          >
            {ACTION_LABELS.reopen}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="send-action-button" ref={containerRef} data-action={effectiveAction}>
      <div className="send-action-button__main">
        {/* Main button area - tap/click to execute */}
        <button
          type="button"
          className="send-action-button__action"
          disabled={disabled}
          {...longPressHandlers}
          aria-label={ACTION_DESCRIPTIONS[effectiveAction]}
        >
          {ACTION_LABELS[effectiveAction]}
        </button>

        {/* Chevron for dropdown (desktop) */}
        <button
          type="button"
          className="send-action-button__chevron"
          onClick={handleChevronClick}
          disabled={disabled}
          aria-label="Choose action"
          aria-expanded={isOpen}
          aria-haspopup="listbox"
        >
          <span className={`send-action-button__chevron-icon ${isOpen ? 'open' : ''}`}>
            ▾
          </span>
        </button>
      </div>

      {/* Dropdown menu */}
      {isOpen && (
        <div
          className="send-action-button__dropdown"
          ref={dropdownRef}
          role="listbox"
          aria-label="Action options"
        >
          {filteredActions.map((actionOption) => (
            <button
              key={actionOption}
              type="button"
              className={`send-action-button__option ${action === actionOption ? 'selected' : ''}`}
              onClick={() => handleSelectAction(actionOption)}
              role="option"
              aria-selected={action === actionOption}
            >
              <span className="send-action-button__option-label">
                {ACTION_LABELS[actionOption]}
              </span>
              <span className="send-action-button__option-desc">
                {ACTION_DESCRIPTIONS[actionOption]}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default SendActionButton;
