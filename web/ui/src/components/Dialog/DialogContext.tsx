/**
 * DialogContext - Context and provider for showing confirm/alert dialogs.
 *
 * Provides a hook `useDialog` that returns methods to show dialogs:
 * - confirm(options) - Shows a confirmation dialog, returns Promise<boolean>
 * - alert(options) - Shows an alert dialog, returns Promise<void>
 *
 * Usage:
 * ```tsx
 * // Wrap your app with DialogProvider
 * <DialogProvider>
 *   <App />
 * </DialogProvider>
 *
 * // In any component:
 * const { confirm, alert } = useDialog();
 *
 * // Show a confirmation
 * const confirmed = await confirm({
 *   title: 'Delete item?',
 *   message: 'This action cannot be undone.',
 *   confirmText: 'Delete',
 *   variant: 'danger',
 * });
 * if (confirmed) { ... }
 *
 * // Show an alert
 * await alert({
 *   title: 'Error',
 *   message: 'Something went wrong.',
 * });
 * ```
 */

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  type ReactNode,
} from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import './Dialog.css';

// Dialog variant for styling
export type DialogVariant = 'default' | 'danger' | 'warning' | 'success';

// Base options for all dialogs
export interface DialogOptions {
  /** Dialog title */
  title?: string;
  /** Dialog message (can be string or ReactNode) */
  message: ReactNode;
  /** Visual variant */
  variant?: DialogVariant;
}

// Options specific to confirm dialogs
export interface ConfirmOptions extends DialogOptions {
  /** Text for the confirm button (default: "Confirm") */
  confirmText?: string;
  /** Text for the cancel button (default: "Cancel") */
  cancelText?: string;
}

// Options specific to alert dialogs
export interface AlertOptions extends DialogOptions {
  /** Text for the OK button (default: "OK") */
  okText?: string;
}

// Internal state for the active dialog - using union type for type safety
type DialogState =
  | { type: 'confirm'; options: ConfirmOptions; resolve: (value: boolean) => void }
  | { type: 'alert'; options: AlertOptions; resolve: () => void };

// Context value type
interface DialogContextValue {
  confirm: (options: ConfirmOptions) => Promise<boolean>;
  alert: (options: AlertOptions) => Promise<void>;
}

// Create context with undefined default (will throw if used outside provider)
const DialogContext = createContext<DialogContextValue | undefined>(undefined);

/**
 * Hook to access dialog methods.
 * Must be used within a DialogProvider.
 */
export function useDialog(): DialogContextValue {
  const context = useContext(DialogContext);
  if (!context) {
    throw new Error('useDialog must be used within a DialogProvider');
  }
  return context;
}

/**
 * DialogProvider - Provides dialog context and renders the dialog modal.
 */
export function DialogProvider({ children }: { children: ReactNode }) {
  const [dialog, setDialog] = useState<DialogState | null>(null);

  // Show a confirmation dialog
  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      setDialog({
        type: 'confirm',
        options,
        resolve,
      });
    });
  }, []);

  // Show an alert dialog
  const alert = useCallback((options: AlertOptions): Promise<void> => {
    return new Promise((resolve) => {
      setDialog({
        type: 'alert',
        options,
        resolve,
      });
    });
  }, []);

  // Handle confirm action
  const handleConfirm = useCallback(() => {
    if (dialog?.type === 'confirm') {
      dialog.resolve(true);
    } else {
      dialog?.resolve();
    }
    setDialog(null);
  }, [dialog]);

  // Handle cancel/close action
  const handleCancel = useCallback(() => {
    if (dialog?.type === 'confirm') {
      dialog.resolve(false);
    } else {
      dialog?.resolve();
    }
    setDialog(null);
  }, [dialog]);

  // Get button class based on variant
  const getConfirmButtonClass = (variant?: DialogVariant) => {
    switch (variant) {
      case 'danger':
        return 'btn-danger';
      case 'warning':
        return 'btn-warning';
      case 'success':
        return 'btn-success';
      default:
        return 'btn-primary';
    }
  };

  const contextValue: DialogContextValue = { confirm, alert };

  return (
    <DialogContext.Provider value={contextValue}>
      {children}

      {/* Render the dialog modal */}
      <Modal
        isOpen={dialog !== null}
        onClose={handleCancel}
        title={dialog?.options.title}
        size="small"
        className={`dialog-modal dialog-modal--${dialog?.options.variant || 'default'}`}
        closeOnBackdropClick={true}
        closeOnEscape={true}
        showCloseButton={false}
      >
        <div className="dialog-message">{dialog?.options.message}</div>
        <ModalFooter>
          {dialog?.type === 'confirm' ? (
            <>
              <button
                type="button"
                className="btn-secondary"
                onClick={handleCancel}
              >
                {(dialog.options as ConfirmOptions).cancelText || 'Cancel'}
              </button>
              <button
                type="button"
                className={getConfirmButtonClass(dialog.options.variant)}
                onClick={handleConfirm}
                autoFocus
              >
                {(dialog.options as ConfirmOptions).confirmText || 'Confirm'}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={handleConfirm}
              autoFocus
            >
              {(dialog?.options as AlertOptions)?.okText || 'OK'}
            </button>
          )}
        </ModalFooter>
      </Modal>
    </DialogContext.Provider>
  );
}
