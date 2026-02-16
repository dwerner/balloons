/**
 * CreatePlanModal component tests
 *
 * Tests for the create plan modal including:
 * - Form rendering and input
 * - Validation
 * - Submit behavior (Create vs Create & Begin)
 * - goalsClient integration
 * - Keyboard shortcuts
 * - Accessibility
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CreatePlanModal } from './CreatePlanModal';
import type { GoalTreeStateServiceClient } from '../../../../generated/client';

// Mock goalsClient
const createMockGoalsClient = (): Partial<GoalTreeStateServiceClient> => ({
  addPlan: jest.fn().mockResolvedValue(null),
});

describe('CreatePlanModal', () => {
  const defaultProps = {
    isOpen: true,
    onClose: jest.fn(),
    goalId: 'goal-123',
    goalTitle: 'Build Authentication System',
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('rendering', () => {
    it('renders nothing when isOpen is false', () => {
      render(<CreatePlanModal {...defaultProps} isOpen={false} />);
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('renders the modal when isOpen is true', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByRole('dialog')).toBeInTheDocument();
    });

    it('displays the title "New Plan"', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByText('New Plan')).toBeInTheDocument();
    });

    it('displays the goal info section', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByText('Goal')).toBeInTheDocument();
      expect(screen.getByText('Build Authentication System')).toBeInTheDocument();
    });

    it('renders title input field', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByPlaceholderText('Plan title...')).toBeInTheDocument();
    });

    it('renders description textarea', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByPlaceholderText('Plan description...')).toBeInTheDocument();
    });

    it('renders status checkbox checked by default', () => {
      render(<CreatePlanModal {...defaultProps} />);
      const checkbox = screen.getByRole('checkbox', {
        name: /start as active/i,
      });
      expect(checkbox).toBeChecked();
    });

    it('renders Cancel and Create Plan buttons', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Create Plan' })).toBeInTheDocument();
    });

    it('renders Create & Begin button when onBeginSession is provided', () => {
      render(
        <CreatePlanModal {...defaultProps} onBeginSession={jest.fn()} />
      );
      expect(
        screen.getByRole('button', { name: 'Create & Begin' })
      ).toBeInTheDocument();
    });

    it('does not render Create & Begin button when onBeginSession is not provided', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(
        screen.queryByRole('button', { name: 'Create & Begin' })
      ).not.toBeInTheDocument();
    });
  });

  describe('form input', () => {
    it('updates title on input', async () => {
      render(<CreatePlanModal {...defaultProps} />);
      const input = screen.getByPlaceholderText('Plan title...');

      await userEvent.type(input, 'Phase 1: Core Auth');
      expect(input).toHaveValue('Phase 1: Core Auth');
    });

    it('updates description on input', async () => {
      render(<CreatePlanModal {...defaultProps} />);
      const textarea = screen.getByPlaceholderText('Plan description...');

      await userEvent.type(textarea, 'Implement basic auth flow');
      expect(textarea).toHaveValue('Implement basic auth flow');
    });

    it('toggles status checkbox', async () => {
      render(<CreatePlanModal {...defaultProps} />);
      const checkbox = screen.getByRole('checkbox', {
        name: /start as active/i,
      });

      expect(checkbox).toBeChecked();
      await userEvent.click(checkbox);
      expect(checkbox).not.toBeChecked();
    });
  });

  describe('validation', () => {
    it('disables Create Plan button when title is empty', () => {
      render(<CreatePlanModal {...defaultProps} />);
      const createButton = screen.getByRole('button', { name: 'Create Plan' });
      expect(createButton).toBeDisabled();
    });

    it('enables Create Plan button when title has content', async () => {
      render(<CreatePlanModal {...defaultProps} />);
      const input = screen.getByPlaceholderText('Plan title...');

      await userEvent.type(input, 'Test Plan');
      const createButton = screen.getByRole('button', { name: 'Create Plan' });
      expect(createButton).toBeEnabled();
    });

    it('disables Create & Begin button when title is empty', () => {
      render(
        <CreatePlanModal {...defaultProps} onBeginSession={jest.fn()} />
      );
      const beginButton = screen.getByRole('button', { name: 'Create & Begin' });
      expect(beginButton).toBeDisabled();
    });
  });

  describe('submit behavior', () => {
    it('calls onSubmit with correct data on Create Plan click', async () => {
      const onSubmit = jest.fn();
      render(<CreatePlanModal {...defaultProps} onSubmit={onSubmit} />);

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Test Plan'
      );
      await userEvent.type(
        screen.getByPlaceholderText('Plan description...'),
        'Test Description'
      );

      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(onSubmit).toHaveBeenCalledWith({
          goalId: 'goal-123',
          title: 'Test Plan',
          description: 'Test Description',
          status: 'active',
          beginSession: false,
        });
      });
    });

    it('calls onSubmit with draft status when checkbox is unchecked', async () => {
      const onSubmit = jest.fn();
      render(<CreatePlanModal {...defaultProps} onSubmit={onSubmit} />);

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Draft Plan'
      );
      await userEvent.click(
        screen.getByRole('checkbox', { name: /start as active/i })
      );

      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(onSubmit).toHaveBeenCalledWith(
          expect.objectContaining({
            status: 'draft',
          })
        );
      });
    });

    it('calls onClose after successful submit', async () => {
      const onClose = jest.fn();
      render(<CreatePlanModal {...defaultProps} onClose={onClose} />);

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Test Plan'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(onClose).toHaveBeenCalled();
      });
    });

    it('calls onBeginSession on Create & Begin click', async () => {
      const onBeginSession = jest.fn();
      render(
        <CreatePlanModal {...defaultProps} onBeginSession={onBeginSession} />
      );

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Session Plan'
      );
      await userEvent.click(
        screen.getByRole('button', { name: 'Create & Begin' })
      );

      await waitFor(() => {
        expect(onBeginSession).toHaveBeenCalledWith(
          expect.any(String), // planId
          'Session Plan'
        );
      });
    });

    it('does not call onBeginSession on regular Create click', async () => {
      const onBeginSession = jest.fn();
      render(
        <CreatePlanModal {...defaultProps} onBeginSession={onBeginSession} />
      );

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Regular Plan'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(onBeginSession).not.toHaveBeenCalled();
      });
    });
  });

  describe('goalsClient integration', () => {
    it('calls goalsClient.addPlan with correct data', async () => {
      const mockClient = createMockGoalsClient();
      render(
        <CreatePlanModal
          {...defaultProps}
          goalsClient={mockClient as GoalTreeStateServiceClient}
        />
      );

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'API Plan'
      );
      await userEvent.type(
        screen.getByPlaceholderText('Plan description...'),
        'API Description'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(mockClient.addPlan).toHaveBeenCalledWith({
          id: expect.any(String),
          goal_id: 'goal-123',
          title: 'API Plan',
          description: 'API Description',
          status: 'active',
        });
      });
    });

    it('shows error when goalsClient.addPlan fails', async () => {
      const mockClient = createMockGoalsClient();
      (mockClient.addPlan as jest.Mock).mockRejectedValue(
        new Error('Network error')
      );

      render(
        <CreatePlanModal
          {...defaultProps}
          goalsClient={mockClient as GoalTreeStateServiceClient}
        />
      );

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Failing Plan'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toHaveTextContent('Network error');
      });
    });

    it('does not close modal on error', async () => {
      const mockClient = createMockGoalsClient();
      const onClose = jest.fn();
      (mockClient.addPlan as jest.Mock).mockRejectedValue(new Error('Failed'));

      render(
        <CreatePlanModal
          {...defaultProps}
          onClose={onClose}
          goalsClient={mockClient as GoalTreeStateServiceClient}
        />
      );

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Error Plan'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe('keyboard shortcuts', () => {
    it('submits on Enter in title field', async () => {
      const onSubmit = jest.fn();
      render(<CreatePlanModal {...defaultProps} onSubmit={onSubmit} />);

      const input = screen.getByPlaceholderText('Plan title...');
      await userEvent.type(input, 'Enter Plan{Enter}');

      await waitFor(() => {
        expect(onSubmit).toHaveBeenCalled();
      });
    });

    it('closes modal on Escape key', async () => {
      const onClose = jest.fn();
      render(<CreatePlanModal {...defaultProps} onClose={onClose} />);

      fireEvent.keyDown(screen.getByRole('dialog').parentElement!, {
        key: 'Escape',
      });

      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('close behavior', () => {
    it('calls onClose when Cancel button is clicked', async () => {
      const onClose = jest.fn();
      render(<CreatePlanModal {...defaultProps} onClose={onClose} />);

      await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(onClose).toHaveBeenCalled();
    });

    it('calls onClose when backdrop is clicked', async () => {
      const onClose = jest.fn();
      render(<CreatePlanModal {...defaultProps} onClose={onClose} />);

      // Click on the overlay (backdrop)
      const overlay = screen.getByRole('dialog').parentElement;
      await userEvent.click(overlay!);
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('loading state', () => {
    it('disables all inputs while submitting', async () => {
      const onSubmit = jest.fn(
        () => new Promise((resolve) => setTimeout(resolve, 100))
      );
      render(<CreatePlanModal {...defaultProps} onSubmit={onSubmit} />);

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Loading Plan'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      // Check that inputs are disabled during submit
      expect(screen.getByPlaceholderText('Plan title...')).toBeDisabled();
      expect(screen.getByPlaceholderText('Plan description...')).toBeDisabled();
      expect(
        screen.getByRole('checkbox', { name: /start as active/i })
      ).toBeDisabled();
    });

    it('shows "Creating..." text on buttons while submitting', async () => {
      const onSubmit = jest.fn(
        () => new Promise((resolve) => setTimeout(resolve, 100))
      );
      render(
        <CreatePlanModal
          {...defaultProps}
          onSubmit={onSubmit}
          onBeginSession={jest.fn()}
        />
      );

      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Loading Plan'
      );
      await userEvent.click(screen.getByRole('button', { name: 'Create Plan' }));

      await waitFor(() => {
        expect(screen.getAllByText('Creating...')).toHaveLength(2);
      });
    });
  });

  describe('form reset', () => {
    it('resets form when modal reopens', async () => {
      const { rerender } = render(<CreatePlanModal {...defaultProps} />);

      // Fill in the form
      await userEvent.type(
        screen.getByPlaceholderText('Plan title...'),
        'Dirty Form'
      );
      await userEvent.type(
        screen.getByPlaceholderText('Plan description...'),
        'Some description'
      );
      await userEvent.click(
        screen.getByRole('checkbox', { name: /start as active/i })
      );

      // Close and reopen the modal
      rerender(<CreatePlanModal {...defaultProps} isOpen={false} />);
      rerender(<CreatePlanModal {...defaultProps} isOpen={true} />);

      // Form should be reset
      expect(screen.getByPlaceholderText('Plan title...')).toHaveValue('');
      expect(screen.getByPlaceholderText('Plan description...')).toHaveValue('');
      expect(
        screen.getByRole('checkbox', { name: /start as active/i })
      ).toBeChecked();
    });
  });

  describe('accessibility', () => {
    it('focuses title input on mount', async () => {
      render(<CreatePlanModal {...defaultProps} />);

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Plan title...')).toHaveFocus();
      });
    });

    it('has accessible labels for form fields', () => {
      render(<CreatePlanModal {...defaultProps} />);

      expect(screen.getByText('Title')).toBeInTheDocument();
      expect(screen.getByText('Description (optional)')).toBeInTheDocument();
    });

    it('has aria-describedby attribute', () => {
      render(<CreatePlanModal {...defaultProps} />);
      expect(screen.getByRole('dialog')).toHaveAttribute(
        'aria-describedby',
        'create-plan-description'
      );
    });
  });
});
