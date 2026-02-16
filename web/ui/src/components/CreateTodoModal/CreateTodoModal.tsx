/**
 * CreateTodoModal - Modal for creating a new todo under a plan
 *
 * React port of widgets/create_entity_modal.py CreateTodoModal.
 * Features:
 * - Title input field
 * - Description textarea (optional)
 * - Spike checkbox with conditional timebox input
 * - "Create Todo" and "Create & Begin" buttons
 * - Dismiss on Escape or backdrop click
 * - Calls goalsClient.addTodo() on submit
 * - If "Create & Begin", also triggers session creation
 */

import React, { useState, useCallback, useRef, useEffect, memo } from 'react';
import { Modal, ModalFooter } from '../Modal/Modal';
import type { GoalTreeStateServiceClient } from '../../../../generated/client';
import './CreateTodoModal.css';

/** Result returned when todo is created */
export interface CreateTodoResult {
  planId: string;
  title: string;
  description: string;
  isSpike: boolean;
  timeboxMinutes: number | null;
  beginSession: boolean;
}

export interface CreateTodoModalProps {
  /** Whether the modal is open */
  isOpen: boolean;

  /** Called when the modal should close (cancel or after submit) */
  onClose: () => void;

  /** The plan ID to create the todo under */
  planId: string;

  /** The plan title (for display) */
  planTitle: string;

  /** Goals client for API calls (optional - if not provided, onSubmit must handle creation) */
  goalsClient?: GoalTreeStateServiceClient;

  /** Called when todo is created successfully */
  onSubmit?: (result: CreateTodoResult) => void | Promise<void>;

  /** Called when "Create & Begin" is clicked to create a bound session */
  onBeginSession?: (
    todoId: string,
    todoTitle: string,
    todoDescription: string,
    planId: string,
    planTitle: string,
    isSpike: boolean,
    timeboxMinutes: number | null,
  ) => void | Promise<void>;
}

/**
 * Modal for creating a new todo under a plan.
 */
export const CreateTodoModal = memo(function CreateTodoModal({
  isOpen,
  onClose,
  planId,
  planTitle,
  goalsClient,
  onSubmit,
  onBeginSession,
}: CreateTodoModalProps) {
  // Form state
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [isSpike, setIsSpike] = useState(false);
  const [timeboxMinutes, setTimeboxMinutes] = useState('30');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Ref for title input to focus on mount
  const titleInputRef = useRef<HTMLInputElement>(null);

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      setTitle('');
      setDescription('');
      setIsSpike(false);
      setTimeboxMinutes('30');
      setError(null);
      setIsSubmitting(false);
      // Focus title input after a short delay to ensure modal is rendered
      setTimeout(() => {
        titleInputRef.current?.focus();
      }, 50);
    }
  }, [isOpen]);

  // Generate a unique ID for the todo
  const generateId = useCallback((): string => {
    return `todo_${Date.now().toString(36)}_${Math.random().toString(36).substr(2, 9)}`;
  }, []);

  // Parse timebox value
  const parseTimeboxMinutes = useCallback((): number | null => {
    if (!isSpike || !timeboxMinutes.trim()) {
      return null;
    }
    const parsed = parseInt(timeboxMinutes.trim(), 10);
    return isNaN(parsed) ? null : parsed;
  }, [isSpike, timeboxMinutes]);

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

      const result: CreateTodoResult = {
        planId,
        title: trimmedTitle,
        description: description.trim(),
        isSpike,
        timeboxMinutes: parseTimeboxMinutes(),
        beginSession,
      };

      try {
        const todoId = generateId();

        // Call goalsClient if provided
        if (goalsClient) {
          const now = new Date().toISOString();
          await goalsClient.addTodo(
            {
              id: todoId,
              title: trimmedTitle,
              description: description.trim() || '',
              is_spike: isSpike,
              timebox_minutes: parseTimeboxMinutes() ?? undefined,
              status: 'pending',
              created_at: now,
              updated_at: now,
            },
            [planId]
          );
        }

        // Call onSubmit callback if provided
        if (onSubmit) {
          await onSubmit(result);
        }

        // If "Create & Begin", trigger session creation
        if (beginSession && onBeginSession) {
          await onBeginSession(
            todoId,
            trimmedTitle,
            description.trim(),
            planId,
            planTitle,
            isSpike,
            parseTimeboxMinutes(),
          );
        }

        // Close the modal
        onClose();
      } catch (err) {
        console.error('Failed to create todo:', err);
        setError(err instanceof Error ? err.message : 'Failed to create todo');
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      title,
      description,
      isSpike,
      planId,
      goalsClient,
      onSubmit,
      onBeginSession,
      onClose,
      generateId,
      parseTimeboxMinutes,
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
      title="New Todo"
      size="small"
      className="create-todo-modal"
      ariaDescribedBy="create-todo-description"
    >
      <div className="create-todo-modal__content">
        {/* Plan info section */}
        <div className="create-todo-modal__plan-info">
          <span className="create-todo-modal__plan-label">Plan</span>
          <span className="create-todo-modal__plan-title">{planTitle}</span>
        </div>

        {/* Error message */}
        {error && (
          <div className="create-todo-modal__error" role="alert">
            {error}
          </div>
        )}

        {/* Form fields */}
        <div className="create-todo-modal__form">
          {/* Title input */}
          <label className="create-todo-modal__field">
            <span className="create-todo-modal__label">Title</span>
            <input
              ref={titleInputRef}
              type="text"
              className="create-todo-modal__input"
              placeholder="Todo title..."
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={handleTitleKeyDown}
              disabled={isSubmitting}
              autoComplete="off"
            />
          </label>

          {/* Description textarea */}
          <label className="create-todo-modal__field">
            <span className="create-todo-modal__label">Description (optional)</span>
            <textarea
              className="create-todo-modal__textarea"
              placeholder="Describe what needs to be done..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isSubmitting}
              rows={4}
            />
          </label>

          {/* Spike checkbox */}
          <label className="create-todo-modal__checkbox-field">
            <input
              type="checkbox"
              className="create-todo-modal__checkbox"
              checked={isSpike}
              onChange={(e) => setIsSpike(e.target.checked)}
              disabled={isSubmitting}
            />
            <span className="create-todo-modal__checkbox-label">
              This is a spike (timeboxed exploration)
            </span>
          </label>

          {/* Timebox input (shown when spike is checked) */}
          {isSpike && (
            <label className="create-todo-modal__field create-todo-modal__timebox-field">
              <span className="create-todo-modal__label">Timebox (minutes)</span>
              <input
                type="number"
                className="create-todo-modal__input create-todo-modal__timebox-input"
                placeholder="30"
                value={timeboxMinutes}
                onChange={(e) => setTimeboxMinutes(e.target.value)}
                disabled={isSubmitting}
                min={1}
                max={480}
              />
            </label>
          )}
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
          {isSubmitting ? 'Creating...' : 'Create Todo'}
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
});

export default CreateTodoModal;
