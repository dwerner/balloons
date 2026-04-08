/**
 * CreatePlanModal - Modal for creating a new plan under a goal
 *
 * React port of widgets/create_entity_modal.py CreatePlanModal.
 * Features:
 * - Title input field
 * - Description textarea (optional)
 * - Status toggle (draft/active)
 * - "Create" and "Create & Begin" buttons
 * - Dismiss on Escape or backdrop click
 * - Calls goalsClient.addPlan() on submit
 * - If "Create & Begin", also triggers session creation
 */

import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { GoalTreeStateServiceClient } from '../../../../generated/client';
import './CreatePlanModal.css';

// Custom comparison function for memo - prevents re-renders when modal is open
// When modal is open, internal state manages the form, so we only need to re-render
// when isOpen changes from true to false (closing) or false to true (opening)
function arePropsEqual(prevProps: CreatePlanModalProps, nextProps: CreatePlanModalProps): boolean {
  // If modal is open in both prev and next, skip re-render
  // Internal state handles the form values during editing
  if (prevProps.isOpen && nextProps.isOpen) {
    return true;
  }
  // Otherwise use default shallow comparison for memo
  return false;
}

// Result type matching Python CreatePlanResult
export interface CreatePlanResult {
  goalId: string;
  title: string;
  description: string;
  status: 'draft' | 'active';
  beginSession: boolean;
}

export interface CreatePlanModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close */
  onClose: () => void;

  /** Goal ID to create the plan under */
  goalId: string;

  /** Goal title for display */
  goalTitle: string;

  /** Goals client for API calls (optional - if not provided, onSubmit must handle creation) */
  goalsClient?: GoalTreeStateServiceClient;

  /** Callback when plan is created successfully */
  onSubmit?: (result: CreatePlanResult) => void | Promise<void>;

  /** Callback to create a bound session after plan creation */
  onBeginSession?: (planId: string, planTitle: string) => void | Promise<void>;
}

/**
 * Modal for creating a new plan under a goal.
 */
export const CreatePlanModal = memo(function CreatePlanModal({
  isOpen,
  onClose,
  goalId,
  goalTitle,
  goalsClient,
  onSubmit,
  onBeginSession,
}: CreatePlanModalProps) {
  // Form state
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [isActive, setIsActive] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ref for title input to focus on mount
  const titleInputRef = useRef<HTMLInputElement>(null);

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setTitle('');
      setDescription('');
      setIsActive(true);
      setError(null);
      setIsSubmitting(false);
      // Focus title input after a short delay to ensure modal is rendered
      setTimeout(() => {
        titleInputRef.current?.focus();
      }, 50);
    }
  }, [isOpen]);

  // Generate a unique ID for the plan
  const generateId = useCallback((): string => {
    return `plan_${Date.now().toString(36)}_${Math.random().toString(36).substr(2, 9)}`;
  }, []);

  // Submit handler
  const handleSubmit = useCallback(
    async (beginSession: boolean) => {
      // Validate title
      const trimmedTitle = title.trim();
      if (!trimmedTitle) {
        setError('Title is required');
        titleInputRef.current?.focus();
        return;
      }

      setIsSubmitting(true);
      setError(null);

      const result: CreatePlanResult = {
        goalId,
        title: trimmedTitle,
        description: description.trim(),
        status: isActive ? 'active' : 'draft',
        beginSession,
      };

      try {
        const planId = generateId();

        // Call goalsClient if provided
        if (goalsClient) {
          await goalsClient.addPlan({
            id: planId,
            goal_id: goalId,
            title: trimmedTitle,
            description: description.trim(),
            status: isActive ? 'active' : 'draft',
          });
        }

        // Call onSubmit callback if provided
        if (onSubmit) {
          await onSubmit(result);
        }

        // If "Create & Begin", trigger session creation
        if (beginSession && onBeginSession) {
          await onBeginSession(planId, trimmedTitle);
        }

        // Close the modal
        onClose();
      } catch (err) {
        console.error('Failed to create plan:', err);
        setError(err instanceof Error ? err.message : 'Failed to create plan');
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      title,
      description,
      isActive,
      goalId,
      goalsClient,
      onSubmit,
      onBeginSession,
      onClose,
      generateId,
    ]
  );

  // Handle Enter key in title input
  const handleTitleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(false);
      }
    },
    [handleSubmit]
  );

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="New Plan"
      size="small"
      className="create-plan-modal"
      ariaDescribedBy="create-plan-description"
    >
      <div className="create-plan-modal__content">
        {/* Goal info section */}
        <div className="create-plan-modal__goal-info">
          <span className="create-plan-modal__goal-label">Goal</span>
          <span className="create-plan-modal__goal-title">{goalTitle}</span>
        </div>

        {/* Error message */}
        {error && (
          <div className="create-plan-modal__error" role="alert">
            {error}
          </div>
        )}

        {/* Form fields */}
        <div className="create-plan-modal__form">
          {/* Title input */}
          <label className="create-plan-modal__field">
            <span className="create-plan-modal__label">Title</span>
            <input
              ref={titleInputRef}
              type="text"
              className="create-plan-modal__input"
              placeholder="Plan title..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={handleTitleKeyDown}
              disabled={isSubmitting}
              autoComplete="off"
            />
          </label>

          {/* Description textarea */}
          <label className="create-plan-modal__field">
            <span className="create-plan-modal__label">Description (optional)</span>
            <textarea
              className="create-plan-modal__textarea"
              placeholder="Plan description..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isSubmitting}
              rows={4}
            />
          </label>

          {/* Status toggle */}
          <label className="create-plan-modal__checkbox-field">
            <input
              type="checkbox"
              className="create-plan-modal__checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              disabled={isSubmitting}
            />
            <span className="create-plan-modal__checkbox-label">
              Start as active (otherwise draft)
            </span>
          </label>
        </div>
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
          onClick={() => handleSubmit(false)}
          disabled={isSubmitting || !title.trim()}
        >
          {isSubmitting ? 'Creating...' : 'Create Plan'}
        </button>
        {onBeginSession && (
          <button
            type="button"
            className="btn btn-success"
            onClick={() => handleSubmit(true)}
            disabled={isSubmitting || !title.trim()}
          >
            {isSubmitting ? 'Creating...' : 'Create & Begin'}
          </button>
        )}
      </ModalFooter>
    </Modal>
  );
}, arePropsEqual);

export default CreatePlanModal;
