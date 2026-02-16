/**
 * GoalTreeView tests
 *
 * Basic tests for the goal tree view component.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { GoalTreeView } from './GoalTreeView';
import type { GoalInfo, SessionBindingInfo, GoalProgress, GoalTreeStats } from '../../../../generated/types';

// Mock data
const mockGoal: GoalInfo = {
  id: 'goal-1',
  title: 'Test Goal',
  description: 'A test goal',
  weight: 5,
  status: 'active',
  acceptanceCriteria: ['Criterion 1', 'Criterion 2'],
  createdAt: '2024-01-01T00:00:00Z',
  updatedAt: '2024-01-01T00:00:00Z',
  planIds: ['plan-1'],
  childGoalIds: [],
  boundSessionIds: [],
  isExpanded: true,
};

const mockStats: GoalTreeStats = {
  totalGoals: 1,
  activeGoals: 1,
  totalPlans: 1,
  activePlans: 1,
  totalTodos: 2,
  pendingTodos: 1,
  inProgressTodos: 1,
  boundSessions: 0,
  unboundSessions: 0,
};

describe('GoalTreeView', () => {
  it('renders empty state when no goals', () => {
    render(<GoalTreeView initialGoals={[]} />);
    expect(screen.getByText('No goals')).toBeInTheDocument();
  });

  it('renders goals when provided', () => {
    render(<GoalTreeView initialGoals={[mockGoal]} initialStats={mockStats} />);
    expect(screen.getByText('Test Goal')).toBeInTheDocument();
  });

  it('renders header with stats', () => {
    render(<GoalTreeView initialGoals={[mockGoal]} initialStats={mockStats} />);
    expect(screen.getByText(/Goals \(1g, 1\+1t\)/)).toBeInTheDocument();
  });

  it('renders loading state', () => {
    render(<GoalTreeView isLoading={true} />);
    expect(screen.getByText('Loading goals...')).toBeInTheDocument();
  });

  it('calls onSelectEntity when goal is clicked', () => {
    const onSelectEntity = jest.fn();
    render(
      <GoalTreeView
        initialGoals={[mockGoal]}
        initialStats={mockStats}
        onSelectEntity={onSelectEntity}
      />
    );

    fireEvent.click(screen.getByText('Test Goal'));
    expect(onSelectEntity).toHaveBeenCalledWith('goal', 'goal-1');
  });
});

describe('ProgressBar', () => {
  it('renders correct progress', () => {
    const goalWithProgress: GoalInfo = {
      ...mockGoal,
      planIds: [],
    };
    render(<GoalTreeView initialGoals={[goalWithProgress]} initialStats={mockStats} />);

    // Progress bar should show 0/0 when no todos
    expect(screen.getByText('0/0')).toBeInTheDocument();
  });
});
