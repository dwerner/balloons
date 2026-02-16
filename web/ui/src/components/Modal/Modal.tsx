/**
 * Modal - Reusable modal component using React portal
 *
 * A base modal component that provides:
 * - React portal for rendering above other content
 * - Backdrop click to close
 * - Keyboard support (Escape to close)
 * - Responsive sizing for mobile
 * - Focus management (traps focus within modal)
 *
 * Design patterns mirror TUI ModalScreen behavior from widgets/.
 */

import React, {
  useEffect,
  useRef,
  useCallback,
  memo,
  type ReactNode,
  type MouseEvent,
  type KeyboardEvent,
} from 'react';
import { createPortal } from 'react-dom';
import './Modal.css';

// Size variants for the modal
export type ModalSize = 'small' | 'medium' | 'large' | 'full';

// Modal props
export interface ModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close */
  onClose: () => void;

  /** Modal title (shown in header) */
  title?: string;

  /** Modal content */
  children: ReactNode;

  /** Size variant */
  size?: ModalSize;

  /** Whether clicking the backdrop closes the modal (default: true) */
  closeOnBackdropClick?: boolean;

  /** Whether pressing Escape closes the modal (default: true) */
  closeOnEscape?: boolean;

  /** Whether to show the close button in the header (default: true) */
  showCloseButton?: boolean;

  /** Additional class name for the modal dialog */
  className?: string;

  /** Portal container element (default: document.body) */
  portalContainer?: HTMLElement;

  /** Accessibility label for the modal */
  ariaLabel?: string;

  /** ID for the modal description element (for aria-describedby) */
  ariaDescribedBy?: string;
}

// Focus trap: find all focusable elements within a container
function getFocusableElements(container: HTMLElement): HTMLElement[] {
  const focusableSelectors = [
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    'a[href]',
    '[tabindex]:not([tabindex="-1"])',
  ].join(', ');

  return Array.from(container.querySelectorAll<HTMLElement>(focusableSelectors));
}

/**
 * Modal component that renders in a portal.
 */
export const Modal = memo(function Modal({
  isOpen,
  onClose,
  title,
  children,
  size = 'medium',
  closeOnBackdropClick = true,
  closeOnEscape = true,
  showCloseButton = true,
  className = '',
  portalContainer,
  ariaLabel,
  ariaDescribedBy,
}: ModalProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);

  // Store the previously focused element and restore on close
  useEffect(() => {
    if (isOpen) {
      previousActiveElement.current = document.activeElement as HTMLElement;
    } else if (previousActiveElement.current) {
      previousActiveElement.current.focus();
      previousActiveElement.current = null;
    }
  }, [isOpen]);

  // Focus the modal when it opens
  useEffect(() => {
    if (isOpen && modalRef.current) {
      // Focus the first focusable element, or the modal itself
      const focusableElements = getFocusableElements(modalRef.current);
      const firstElement = focusableElements[0];
      if (firstElement) {
        firstElement.focus();
      } else {
        modalRef.current.focus();
      }
    }
  }, [isOpen]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = 'hidden';
      return () => {
        document.body.style.overflow = originalOverflow;
      };
    }
  }, [isOpen]);

  // Handle keyboard events
  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      // Close on Escape
      if (closeOnEscape && event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }

      // Focus trap: handle Tab key
      if (event.key === 'Tab' && modalRef.current) {
        const focusableElements = getFocusableElements(modalRef.current);
        if (focusableElements.length === 0) return;

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (!firstElement || !lastElement) return;

        if (event.shiftKey) {
          // Shift+Tab: go to last element if at first
          if (document.activeElement === firstElement) {
            event.preventDefault();
            lastElement.focus();
          }
        } else {
          // Tab: go to first element if at last
          if (document.activeElement === lastElement) {
            event.preventDefault();
            firstElement.focus();
          }
        }
      }
    },
    [closeOnEscape, onClose]
  );

  // Handle backdrop click
  const handleBackdropClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      // Only close if clicking directly on backdrop (not modal content)
      if (closeOnBackdropClick && event.target === event.currentTarget) {
        onClose();
      }
    },
    [closeOnBackdropClick, onClose]
  );

  // Handle close button click
  const handleCloseClick = useCallback(
    (event: MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      onClose();
    },
    [onClose]
  );

  // Don't render if not open
  if (!isOpen) {
    return null;
  }

  // Determine portal container
  const container = portalContainer || document.body;

  // Modal content
  const modalContent = (
    <div
      className="modal-overlay"
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
      role="presentation"
    >
      <div
        ref={modalRef}
        className={`modal-dialog modal-dialog--${size} ${className}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel || title}
        aria-describedby={ariaDescribedBy}
        tabIndex={-1}
      >
        {/* Header */}
        {(title || showCloseButton) && (
          <div className="modal-header">
            {title && <h2 className="modal-title">{title}</h2>}
            {showCloseButton && (
              <button
                type="button"
                className="modal-close-button"
                onClick={handleCloseClick}
                aria-label="Close modal"
              >
                <CloseIcon />
              </button>
            )}
          </div>
        )}

        {/* Body */}
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );

  // Render in portal
  return createPortal(modalContent, container);
});

/**
 * Close icon component (X).
 */
function CloseIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

/**
 * ModalHeader - Optional component for custom header content.
 */
export interface ModalHeaderProps {
  children: ReactNode;
  className?: string;
}

export const ModalHeader = memo(function ModalHeader({
  children,
  className = '',
}: ModalHeaderProps) {
  return <div className={`modal-header ${className}`.trim()}>{children}</div>;
});

/**
 * ModalBody - Optional component for body content with padding.
 */
export interface ModalBodyProps {
  children: ReactNode;
  className?: string;
}

export const ModalBody = memo(function ModalBody({
  children,
  className = '',
}: ModalBodyProps) {
  return <div className={`modal-body ${className}`.trim()}>{children}</div>;
});

/**
 * ModalFooter - Optional component for footer with action buttons.
 */
export interface ModalFooterProps {
  children: ReactNode;
  className?: string;
}

export const ModalFooter = memo(function ModalFooter({
  children,
  className = '',
}: ModalFooterProps) {
  return <div className={`modal-footer ${className}`.trim()}>{children}</div>;
});

export default Modal;
