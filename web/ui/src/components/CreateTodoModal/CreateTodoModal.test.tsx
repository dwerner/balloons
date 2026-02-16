/**
 * CreateTodoModal component tests
 *
 * Tests for the CreateTodoModal component including:
 * - Form rendering and field states
 * - Title validation
 * - Spike checkbox and timebox interaction
 * - Submit and close behavior
 * - API integration
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreateTodoModal, type CreateTodoResult } from './CreateTodoModal';

// Mock goalsClient
const createMockGoalsClient = () => ({
  addTodo: jest.fn().mockResolvedValue(null),
});

describe('CreateTodoModal', () => {
  const defaultProps = {
    isOpen: true,
    onClose: jest.fn(),
    planId: 'plan-123',
    planTitle: 'Test Plan',
    onSubmit: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders nothing when isOpen is false', () => {
      render(<CreateTodoModal {...defaultProps} isOpen={false} />);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('renders the modal when isOpen is true', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('renders the modal title', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.getByText('New Todo')).toBeInTheDocument();
    });

    it('renders the plan title', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.getByText('Test Plan')).toBeInTheDocument();
    });

    it('renders all form fields', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.getByText('Title')).toBeInTheDocument();
      expect(screen.getByText('Description (optional)')).toBeInTheDocument();
      expect(screen.getByText('This is a spike (timeboxed exploration)')).toBeInTheDocument();
    });

    it('renders Cancel and Create Todo buttons', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.getByText('Cancel')).toBeInTheDocument();
      expect(screen.getByText('Create Todo')).toBeInTheDocument();
    });

    it('renders Create & Begin button only when onBeginSession is provided', () => {
      // Without onBeginSession
      const { rerender } = render(<CreateTodoModal {...defaultProps} />);
      expect(screen.queryByText('Create & Begin')).not.toBeInTheDocument();

      // With onBeginSession
      rerender(<CreateTodoModal {...defaultProps} onBeginSession={jest.fn()} />);
      expect(screen.getByText('Create & Begin')).toBeInTheDocument();
    });
  });

  describe('form validation', () => {
    it('disables submit button when title is empty', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.getByText('Create Todo')).toBeDisabled();
    });

    it('enables submit button when title has content', async () => {
      render(<CreateTodoModal {...defaultProps} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'New Todo');

      expect(screen.getByText('Create Todo')).not.toBeDisabled();
    });
  });

  describe('spike checkbox', () => {
    it('does not show timebox input by default', () => {
      render(<CreateTodoModal {...defaultProps} />);
      expect(screen.queryByText('Timebox (minutes)')).not.toBeInTheDocument();
    });

    it('shows timebox input when spike is checked', async () => {
      render(<CreateTodoModal {...defaultProps} />);

      await userEvent.click(screen.getByText('This is a spike (timeboxed exploration)'));

      expect(screen.getByText('Timebox (minutes)')).toBeInTheDocument();
    });

    it('hides timebox input when spike is unchecked', async () => {
      render(<CreateTodoModal {...defaultProps} />);

      // Check and then uncheck
      const spikeLabel = screen.getByText('This is a spike (timeboxed exploration)');
      await userEvent.click(spikeLabel);
      expect(screen.getByText('Timebox (minutes)')).toBeInTheDocument();

      await userEvent.click(spikeLabel);
      expect(screen.queryByText('Timebox (minutes)')).not.toBeInTheDocument();
    });

    it('has default timebox value of 30', async () => {
      render(<CreateTodoModal {...defaultProps} />);

      await userEvent.click(screen.getByText('This is a spike (timeboxed exploration)'));

      expect(screen.getByPlaceholderText('30')).toHaveValue(30);
    });
  });

  describe('close behavior', () => {
    it('calls onClose when Cancel is clicked', async () => {
      const onClose = jest.fn();
      render(<CreateTodoModal {...defaultProps} onClose={onClose} />);

      await userEvent.click(screen.getByText('Cancel'));

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('calls onClose when Escape is pressed', async () => {
      const onClose = jest.fn();
      render(<CreateTodoModal {...defaultProps} onClose={onClose} />);

      fireEvent.keyDown(screen.getByRole('dialog').parentElement!, {
        key: 'Escape',
      });

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('calls onClose when backdrop is clicked', async () => {
      const onClose = jest.fn();
      render(<CreateTodoModal {...defaultProps} onClose={onClose} />);

      const overlay = screen.getByRole('dialog').parentElement;
      await userEvent.click(overlay!);

      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });

  describe('submit behavior', () => {
    it('calls onSubmit with correct data when Create Todo is clicked', async () => {
      const onSubmit = jest.fn();
      render(<CreateTodoModal {...defaultProps} onSubmit={onSubmit} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'My New Todo');
      await userEvent.type(
        screen.getByPlaceholderText('Describe what needs to be done...'),
        'Description text'
      );
      await userEvent.click(screen.getByText('Create Todo'));

      expect(onSubmit).toHaveBeenCalledWith({
        planId: 'plan-123',
        title: 'My New Todo',
        description: 'Description text',
        isSpike: false,
        timeboxMinutes: null,
        beginSession: false,
      } as CreateTodoResult);
    });

    it('calls onSubmit with spike data when spike is checked', async () => {
      const onSubmit = jest.fn();
      render(<CreateTodoModal {...defaultProps} onSubmit={onSubmit} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'Spike Task');
      await userEvent.click(screen.getByText('This is a spike (timeboxed exploration)'));
      await userEvent.clear(screen.getByPlaceholderText('30'));
      await userEvent.type(screen.getByPlaceholderText('30'), '45');
      await userEvent.click(screen.getByText('Create Todo'));

      expect(onSubmit).toHaveBeenCalledWith({
        planId: 'plan-123',
        title: 'Spike Task',
        description: '',
        isSpike: true,
        timeboxMinutes: 45,
        beginSession: false,
      } as CreateTodoResult);
    });

    it('calls onBeginSession when Create & Begin is clicked', async () => {
      const onBeginSession = jest.fn();
      render(<CreateTodoModal {...defaultProps} onBeginSession={onBeginSession} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'Begin Task');
      await userEvent.click(screen.getByText('Create & Begin'));

      // onBeginSession is called with todoId and title
      expect(onBeginSession).toHaveBeenCalledWith(
        expect.stringMatching(/^todo_/), // Generated ID starts with todo_
        'Begin Task'
      );
    });

    it('calls onClose after successful submit', async () => {
      const onClose = jest.fn();
      render(<CreateTodoModal {...defaultProps} onClose={onClose} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'Test');
      await userEvent.click(screen.getByText('Create Todo'));

      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('submits on Enter key in title field', async () => {
      const onSubmit = jest.fn();
      render(<CreateTodoModal {...defaultProps} onSubmit={onSubmit} />);

      const titleInput = screen.getByPlaceholderText('Todo title...');
      await userEvent.type(titleInput, 'Enter Submit{enter}');

      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'Enter Submit',
        })
      );
    });
  });

  describe('API integration', () => {
    it('calls goalsClient.addTodo when goalsClient is provided', async () => {
      const mockClient = createMockGoalsClient();
      render(<CreateTodoModal {...defaultProps} goalsClient={mockClient as any} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'API Todo');
      await userEvent.click(screen.getByText('Create Todo'));

      await waitFor(() => {
        expect(mockClient.addTodo).toHaveBeenCalledWith(
          {
            id: expect.stringMatching(/^todo_/),
            title: 'API Todo',
            description: undefined,
            is_spike: false,
            timebox_minutes: undefined,
            status: 'pending',
          },
          ['plan-123']
        );
      });
    });

    it('shows error when API call fails', async () => {
      const mockClient = createMockGoalsClient();
      mockClient.addTodo.mockRejectedValue(new Error('Network error'));

      render(<CreateTodoModal {...defaultProps} goalsClient={mockClient as any} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'Failing Todo');
      await userEvent.click(screen.getByText('Create Todo'));

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
    });

    it('disables buttons during submission', async () => {
      const mockClient = createMockGoalsClient();
      // Make API call hang
      mockClient.addTodo.mockImplementation(() => new Promise(() => {}));

      render(<CreateTodoModal {...defaultProps} goalsClient={mockClient as any} />);

      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'Loading Todo');
      await userEvent.click(screen.getByText('Create Todo'));

      await waitFor(() => {
        expect(screen.getByText('Creating...')).toBeInTheDocument();
        expect(screen.getByText('Creating...')).toBeDisabled();
        expect(screen.getByText('Cancel')).toBeDisabled();
      });
    });
  });

  describe('form reset', () => {
    it('resets form when modal reopens', async () => {
      const { rerender } = render(<CreateTodoModal {...defaultProps} />);

      // Fill in form
      await userEvent.type(screen.getByPlaceholderText('Todo title...'), 'Previous Value');
      await userEvent.click(screen.getByText('This is a spike (timeboxed exploration)'));

      // Close and reopen
      rerender(<CreateTodoModal {...defaultProps} isOpen={false} />);
      rerender(<CreateTodoModal {...defaultProps} isOpen={true} />);

      // Form should be reset
      expect(screen.getByPlaceholderText('Todo title...')).toHaveValue('');
      expect(screen.queryByText('Timebox (minutes)')).not.toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('focuses title input when modal opens', async () => {
      render(<CreateTodoModal {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Todo title...')).toHaveFocus();
      });
    });

    it('has proper aria attributes', () => {
      render(<CreateTodoModal {...defaultProps} />);
      const dialog = screen.getByRole('dialog');
      expect(dialog).toHaveAttribute('aria-modal', 'true');
    });
  });
});
