/**
 * GoalTreeView - Goal-centric tree view organizing by goals -> plans -> todos
 *
 * React equivalent of widgets/goal_tree.py. Shows the work being done (goals, plans, todos)
 * with sessions shown as children of the entities they're bound to.
 *
 * Features:
 * - Goal nodes with progress bars (completed/total todos)
 * - Plan nodes with status indicators (draft/active/completed)
 * - Todo nodes with status (pending/in_progress/completed/blocked)
 * - Session nodes bound to entities with role indicators
 * - Action buttons: [+plan], [+todo], [+session], [done], [move], [unbind], [+rollup]
 * - Unbound sessions section
 */

import React, { useState, useCallback, useMemo, memo, useEffect } from 'react';
import type {
  GoalInfo,
  PlanInfo,
  TodoInfo,
  SessionBindingInfo,
  GoalProgress,
  GoalTreeStats,
  GoalTreeEventData,
} from '../../../../generated/balloons-client';
import { GoalTreeStateServiceClient } from '../../../../generated/client';
import './GoalTreeView.css';

// Role abbreviation mapping (mirrors core/goal_commands.py ROLE_ABBREV)
const ROLE_ABBREV: Record<string, string> = {
  implementation: 'impl',
  planning: 'plan',
  interview: 'int',
  postmortem: 'post',
  exploration: 'exp',
};

// Format token count as kt
function formatKt(tokens: number): string {
  if (tokens <= 0) return '';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

// Arrow icon component
function Arrow({ open, color }: { open: boolean; color?: string }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke={color || 'currentColor'}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`goal-tree-arrow ${open ? 'goal-tree-arrow--open' : ''}`}
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

// Progress bar component for goals
function ProgressBar({ completed, total }: { completed: number; total: number }) {
  const percentage = total > 0 ? (completed / total) * 100 : 0;
  const filledBlocks = total > 0 ? Math.round((completed / total) * 5) : 0;
  const emptyBlocks = 5 - filledBlocks;

  return (
    <span className="goal-tree-progress">
      <span className="goal-tree-progress__bar">
        {'█'.repeat(filledBlocks)}
        {'░'.repeat(emptyBlocks)}
      </span>
      <span className="goal-tree-progress__count">
        {completed}/{total}
      </span>
    </span>
  );
}

// Status icon component
function StatusIcon({ status, type }: { status: string; type: 'goal' | 'plan' | 'todo' }) {
  const icons: Record<string, Record<string, { icon: string; className: string }>> = {
    goal: {
      active: { icon: '●', className: 'status--active' },
      completed: { icon: '✓', className: 'status--completed' },
      superseded: { icon: '→', className: 'status--superseded' },
      abandoned: { icon: '✗', className: 'status--abandoned' },
    },
    plan: {
      draft: { icon: '◌', className: 'status--draft' },
      active: { icon: '●', className: 'status--active' },
      completed: { icon: '✓', className: 'status--completed' },
      abandoned: { icon: '✗', className: 'status--abandoned' },
    },
    todo: {
      pending: { icon: '○', className: 'status--pending' },
      in_progress: { icon: '◐', className: 'status--in-progress' },
      completed: { icon: '✓', className: 'status--completed' },
      blocked: { icon: '⊘', className: 'status--blocked' },
      abandoned: { icon: '✗', className: 'status--abandoned' },
    },
  };

  const config = icons[type]?.[status] || { icon: '○', className: '' };

  return <span className={`goal-tree-status ${config.className}`}>{config.icon}</span>;
}

// Action button component
function ActionButton({
  label,
  onClick,
  variant = 'default',
}: {
  label: string;
  onClick: (e: React.MouseEvent) => void;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'cyan' | 'magenta' | 'yellow';
}) {
  return (
    <button
      className={`goal-tree-action goal-tree-action--${variant}`}
      onClick={(e) => {
        e.stopPropagation();
        onClick(e);
      }}
    >
      {label}
    </button>
  );
}

// Session node component
interface SessionNodeProps {
  session: SessionBindingInfo;
  isHovered: boolean;
  onSelect: () => void;
  onMove?: () => void;
  onUnbind?: () => void;
}

const SessionNode = memo(function SessionNode({
  session,
  isHovered,
  onSelect,
  onMove,
  onUnbind,
}: SessionNodeProps) {
  const tokenStr = formatKt(session.tokenCount);
  const roleAbbrev = ROLE_ABBREV[session.bindingRole] || '';

  return (
    <li className="goal-tree-node goal-tree-node--session">
      <div
        className={`goal-tree-node__content ${session.isCurrent ? 'goal-tree-node__content--current' : ''}`}
        onClick={onSelect}
      >
        <span className="goal-tree-node__spacer" />

        {tokenStr && <span className="goal-tree-node__tokens">{tokenStr}</span>}

        {session.isCurrent && <span className="goal-tree-node__current-indicator">→</span>}

        {session.isStreaming && <span className="goal-tree-node__streaming">●</span>}

        {session.forkStatus === 'merged' ? (
          <span className="goal-tree-node__fork-merged">✓</span>
        ) : session.forkStatus ? (
          <span className="goal-tree-node__fork-active">↳</span>
        ) : null}

        <span className="goal-tree-node__icon">📁</span>
        <span className="goal-tree-node__label">{session.name}</span>

        {roleAbbrev && <span className="goal-tree-node__role">[{roleAbbrev}]</span>}

        {isHovered && (
          <span className="goal-tree-node__actions">
            {onMove && (
              <ActionButton
                label={session.bindingRole ? '[move]' : '[bind]'}
                onClick={() => onMove()}
                variant={session.bindingRole ? 'warning' : 'success'}
              />
            )}
            {onUnbind && session.bindingRole && (
              <ActionButton label="[unbind]" onClick={() => onUnbind()} variant="danger" />
            )}
          </span>
        )}
      </div>
    </li>
  );
});

// Todo node component
interface TodoNodeProps {
  todo: TodoInfo;
  sessions: SessionBindingInfo[];
  isExpanded: boolean;
  isHovered: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onMarkDone?: () => void;
  onMarkUndone?: () => void;
  onNewSession?: () => void;
  onSelectSession: (sessionId: string) => void;
  onMoveSession?: (sessionId: string) => void;
  onUnbindSession?: (sessionId: string) => void;
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
}

const TodoNode = memo(function TodoNode({
  todo,
  sessions,
  isExpanded,
  isHovered,
  onToggle,
  onSelect,
  onMarkDone,
  onMarkUndone,
  onNewSession,
  onSelectSession,
  onMoveSession,
  onUnbindSession,
  hoveredNodeId,
  setHoveredNodeId,
}: TodoNodeProps) {
  const hasSessions = sessions.length > 0;

  return (
    <li className="goal-tree-node goal-tree-node--todo">
      <div
        className="goal-tree-node__content"
        onClick={onSelect}
        onMouseEnter={() => setHoveredNodeId(`todo:${todo.id}`)}
        onMouseLeave={() => setHoveredNodeId(null)}
      >
        <span
          className="goal-tree-node__toggle"
          onClick={(e) => {
            e.stopPropagation();
            onToggle();
          }}
        >
          {hasSessions ? <Arrow open={isExpanded} color="#4ade80" /> : <span className="goal-tree-node__spacer" />}
        </span>

        <StatusIcon status={todo.status} type="todo" />
        <span className="goal-tree-node__label goal-tree-node__label--todo">{todo.title}</span>

        {todo.isSpike && <span className="goal-tree-node__spike">[spike]</span>}
        {todo.priority && todo.priority > 0 && (
          <span className="goal-tree-node__priority">p:{todo.priority.toFixed(1)}</span>
        )}
        {sessions.length > 0 && <span className="goal-tree-node__count">({sessions.length}s)</span>}

        {isHovered && (
          <span className="goal-tree-node__actions">
            {todo.status !== 'completed' && onMarkDone && (
              <ActionButton label="[done]" onClick={() => onMarkDone()} variant="success" />
            )}
            {todo.status === 'completed' && onMarkUndone && (
              <ActionButton label="[!done]" onClick={() => onMarkUndone()} variant="warning" />
            )}
            {onNewSession && <ActionButton label="[+session]" onClick={() => onNewSession()} variant="success" />}
          </span>
        )}
      </div>

      {isExpanded && hasSessions && (
        <ul className="goal-tree-children">
          {sessions.map((session) => (
            <SessionNode
              key={session.sessionId}
              session={session}
              isHovered={hoveredNodeId === `session:${session.sessionId}`}
              onSelect={() => onSelectSession(session.sessionId)}
              onMove={onMoveSession ? () => onMoveSession(session.sessionId) : undefined}
              onUnbind={onUnbindSession ? () => onUnbindSession(session.sessionId) : undefined}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

// Plan node component
interface PlanNodeProps {
  plan: PlanInfo;
  todos: TodoInfo[];
  todoSessions: Map<string, SessionBindingInfo[]>;
  planSessions: SessionBindingInfo[];
  expandedIds: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (type: string, id: string) => void;
  onNewTodo?: () => void;
  onNewSession?: () => void;
  onRollup?: () => void;
  onMarkTodoDone?: (todoId: string) => void;
  onMarkTodoUndone?: (todoId: string) => void;
  onNewTodoSession?: (todoId: string) => void;
  onSelectSession: (sessionId: string) => void;
  onMoveSession?: (sessionId: string) => void;
  onUnbindSession?: (sessionId: string) => void;
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
}

const PlanNode = memo(function PlanNode({
  plan,
  todos,
  todoSessions,
  planSessions,
  expandedIds,
  onToggle,
  onSelect,
  onNewTodo,
  onNewSession,
  onRollup,
  onMarkTodoDone,
  onMarkTodoUndone,
  onNewTodoSession,
  onSelectSession,
  onMoveSession,
  onUnbindSession,
  hoveredNodeId,
  setHoveredNodeId,
}: PlanNodeProps) {
  const hasChildren = todos.length > 0 || planSessions.length > 0;
  const isExpanded = expandedIds.has(plan.id);
  const isHovered = hoveredNodeId === `plan:${plan.id}`;

  return (
    <li className="goal-tree-node goal-tree-node--plan">
      <div
        className="goal-tree-node__content"
        onClick={() => onSelect('plan', plan.id)}
        onMouseEnter={() => setHoveredNodeId(`plan:${plan.id}`)}
        onMouseLeave={() => setHoveredNodeId(null)}
      >
        <span
          className="goal-tree-node__toggle"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(plan.id);
          }}
        >
          {hasChildren ? <Arrow open={isExpanded} color="#22d3ee" /> : <span className="goal-tree-node__spacer" />}
        </span>

        <StatusIcon status={plan.status} type="plan" />
        <span className="goal-tree-node__icon">📋</span>
        <span className="goal-tree-node__label goal-tree-node__label--plan">{plan.title}</span>

        {todos.length > 0 && <span className="goal-tree-node__count">({todos.length}t)</span>}

        {isHovered && (
          <span className="goal-tree-node__actions">
            {onNewTodo && <ActionButton label="[+todo]" onClick={() => onNewTodo()} variant="magenta" />}
            {onRollup && <ActionButton label="[+rollup]" onClick={() => onRollup()} variant="yellow" />}
            {onNewSession && <ActionButton label="[+session]" onClick={() => onNewSession()} variant="success" />}
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <ul className="goal-tree-children">
          {todos.map((todo) => (
            <TodoNode
              key={todo.id}
              todo={todo}
              sessions={todoSessions.get(todo.id) || []}
              isExpanded={expandedIds.has(todo.id)}
              isHovered={hoveredNodeId === `todo:${todo.id}`}
              onToggle={() => onToggle(todo.id)}
              onSelect={() => onSelect('todo', todo.id)}
              onMarkDone={onMarkTodoDone ? () => onMarkTodoDone(todo.id) : undefined}
              onMarkUndone={onMarkTodoUndone ? () => onMarkTodoUndone(todo.id) : undefined}
              onNewSession={onNewTodoSession ? () => onNewTodoSession(todo.id) : undefined}
              onSelectSession={onSelectSession}
              onMoveSession={onMoveSession}
              onUnbindSession={onUnbindSession}
              hoveredNodeId={hoveredNodeId}
              setHoveredNodeId={setHoveredNodeId}
            />
          ))}
          {planSessions.map((session) => (
            <SessionNode
              key={session.sessionId}
              session={session}
              isHovered={hoveredNodeId === `session:${session.sessionId}`}
              onSelect={() => onSelectSession(session.sessionId)}
              onMove={onMoveSession ? () => onMoveSession(session.sessionId) : undefined}
              onUnbind={onUnbindSession ? () => onUnbindSession(session.sessionId) : undefined}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

// Goal node component
interface GoalNodeProps {
  goal: GoalInfo;
  progress: GoalProgress;
  plans: PlanInfo[];
  planTodos: Map<string, TodoInfo[]>;
  planSessions: Map<string, SessionBindingInfo[]>;
  todoSessions: Map<string, SessionBindingInfo[]>;
  goalSessions: SessionBindingInfo[];
  childGoals: GoalInfo[];
  childGoalData: Map<string, {
    progress: GoalProgress;
    plans: PlanInfo[];
    planTodos: Map<string, TodoInfo[]>;
    planSessions: Map<string, SessionBindingInfo[]>;
    todoSessions: Map<string, SessionBindingInfo[]>;
    goalSessions: SessionBindingInfo[];
    childGoals: GoalInfo[];
  }>;
  expandedIds: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (type: string, id: string) => void;
  onNewPlan?: () => void;
  onNewSession?: () => void;
  onRollup?: () => void;
  onNewTodo?: (planId: string) => void;
  onNewPlanSession?: (planId: string) => void;
  onPlanRollup?: (planId: string) => void;
  onMarkTodoDone?: (todoId: string) => void;
  onMarkTodoUndone?: (todoId: string) => void;
  onNewTodoSession?: (todoId: string) => void;
  onSelectSession: (sessionId: string) => void;
  onMoveSession?: (sessionId: string) => void;
  onUnbindSession?: (sessionId: string) => void;
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
  renderGoalNode: (
    goal: GoalInfo,
    data: {
      progress: GoalProgress;
      plans: PlanInfo[];
      planTodos: Map<string, TodoInfo[]>;
      planSessions: Map<string, SessionBindingInfo[]>;
      todoSessions: Map<string, SessionBindingInfo[]>;
      goalSessions: SessionBindingInfo[];
      childGoals: GoalInfo[];
    }
  ) => React.ReactNode;
}

const GoalNode = memo(function GoalNode({
  goal,
  progress,
  plans,
  planTodos,
  planSessions,
  todoSessions,
  goalSessions,
  childGoals,
  childGoalData,
  expandedIds,
  onToggle,
  onSelect,
  onNewPlan,
  onNewSession,
  onRollup,
  onNewTodo,
  onNewPlanSession,
  onPlanRollup,
  onMarkTodoDone,
  onMarkTodoUndone,
  onNewTodoSession,
  onSelectSession,
  onMoveSession,
  onUnbindSession,
  hoveredNodeId,
  setHoveredNodeId,
  renderGoalNode,
}: GoalNodeProps) {
  const hasChildren = plans.length > 0 || goalSessions.length > 0 || childGoals.length > 0;
  const isExpanded = expandedIds.has(goal.id);
  const isHovered = hoveredNodeId === `goal:${goal.id}`;
  const isNestedGoal = goal.parentGoalId != null;

  return (
    <li className="goal-tree-node goal-tree-node--goal">
      <div
        className="goal-tree-node__content"
        onClick={() => onSelect('goal', goal.id)}
        onMouseEnter={() => setHoveredNodeId(`goal:${goal.id}`)}
        onMouseLeave={() => setHoveredNodeId(null)}
      >
        <span
          className="goal-tree-node__toggle"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(goal.id);
          }}
        >
          {hasChildren ? <Arrow open={isExpanded} color="#facc15" /> : <span className="goal-tree-node__spacer" />}
        </span>

        <StatusIcon status={goal.status} type="goal" />
        <span className="goal-tree-node__icon">{isNestedGoal ? '📎' : '🎯'}</span>
        <span className="goal-tree-node__label goal-tree-node__label--goal">{goal.title}</span>

        <ProgressBar completed={progress.completed} total={progress.total} />

        {childGoals.length > 0 && <span className="goal-tree-node__count">({childGoals.length}g)</span>}
        {goalSessions.length > 0 && <span className="goal-tree-node__count">({goalSessions.length}s)</span>}

        {isHovered && (
          <span className="goal-tree-node__actions">
            {onNewPlan && <ActionButton label="[+plan]" onClick={() => onNewPlan()} variant="cyan" />}
            {onRollup && <ActionButton label="[+rollup]" onClick={() => onRollup()} variant="yellow" />}
            {onNewSession && <ActionButton label="[+session]" onClick={() => onNewSession()} variant="success" />}
          </span>
        )}
      </div>

      {isExpanded && hasChildren && (
        <ul className="goal-tree-children">
          {/* Render child goals first */}
          {childGoals.map((childGoal) => {
            const data = childGoalData.get(childGoal.id);
            if (!data) return null;
            return renderGoalNode(childGoal, data);
          })}

          {/* Then plans */}
          {plans.map((plan) => (
            <PlanNode
              key={plan.id}
              plan={plan}
              todos={planTodos.get(plan.id) || []}
              todoSessions={todoSessions}
              planSessions={planSessions.get(plan.id) || []}
              expandedIds={expandedIds}
              onToggle={onToggle}
              onSelect={onSelect}
              onNewTodo={onNewTodo ? () => onNewTodo(plan.id) : undefined}
              onNewSession={onNewPlanSession ? () => onNewPlanSession(plan.id) : undefined}
              onRollup={onPlanRollup ? () => onPlanRollup(plan.id) : undefined}
              onMarkTodoDone={onMarkTodoDone}
              onMarkTodoUndone={onMarkTodoUndone}
              onNewTodoSession={onNewTodoSession}
              onSelectSession={onSelectSession}
              onMoveSession={onMoveSession}
              onUnbindSession={onUnbindSession}
              hoveredNodeId={hoveredNodeId}
              setHoveredNodeId={setHoveredNodeId}
            />
          ))}

          {/* Then sessions bound directly to goal */}
          {goalSessions.map((session) => (
            <SessionNode
              key={session.sessionId}
              session={session}
              isHovered={hoveredNodeId === `session:${session.sessionId}`}
              onSelect={() => onSelectSession(session.sessionId)}
              onMove={onMoveSession ? () => onMoveSession(session.sessionId) : undefined}
              onUnbind={onUnbindSession ? () => onUnbindSession(session.sessionId) : undefined}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

// Unbound sessions section
interface UnboundSectionProps {
  sessions: SessionBindingInfo[];
  isExpanded: boolean;
  onToggle: () => void;
  onSelectSession: (sessionId: string) => void;
  onMoveSession?: (sessionId: string) => void;
  hoveredNodeId: string | null;
  setHoveredNodeId: (id: string | null) => void;
}

const UnboundSection = memo(function UnboundSection({
  sessions,
  isExpanded,
  onToggle,
  onSelectSession,
  onMoveSession,
  hoveredNodeId,
  setHoveredNodeId,
}: UnboundSectionProps) {
  if (sessions.length === 0) return null;

  return (
    <li className="goal-tree-node goal-tree-node--unbound-section">
      <div className="goal-tree-node__content goal-tree-node__content--muted" onClick={onToggle}>
        <span className="goal-tree-node__toggle">
          <Arrow open={isExpanded} color="#888" />
        </span>
        <span className="goal-tree-node__icon">📁</span>
        <span className="goal-tree-node__label">Unbound Sessions ({sessions.length})</span>
      </div>

      {isExpanded && (
        <ul className="goal-tree-children">
          {sessions.map((session) => (
            <SessionNode
              key={session.sessionId}
              session={session}
              isHovered={hoveredNodeId === `session:${session.sessionId}`}
              onSelect={() => onSelectSession(session.sessionId)}
              onMove={onMoveSession ? () => onMoveSession(session.sessionId) : undefined}
            />
          ))}
        </ul>
      )}
    </li>
  );
});

// Main component props
export interface GoalTreeViewProps {
  /** Goals service client for API calls */
  goalsClient?: GoalTreeStateServiceClient;

  /** Initial data (for controlled mode or SSR) */
  initialGoals?: GoalInfo[];
  initialStats?: GoalTreeStats;

  /** Callbacks */
  onSelectSession?: (sessionId: string) => void;
  onSelectEntity?: (entityType: string, entityId: string) => void;
  onNewPlan?: (goalId: string) => void;
  onNewTodo?: (planId: string) => void;
  onNewSession?: (entityType: string, entityId: string) => void;
  onNewBareSession?: () => void;  // Create new unbound session for free-form work
  onMarkTodoDone?: (todoId: string) => void;
  onMarkTodoUndone?: (todoId: string) => void;
  onMoveSession?: (sessionId: string) => void;
  onUnbindSession?: (sessionId: string) => void;
  onRollup?: (scopeType: string, scopeId: string) => void;

  /** Loading state */
  isLoading?: boolean;
}

// Main component
export const GoalTreeView = memo(function GoalTreeView({
  goalsClient,
  initialGoals = [],
  initialStats,
  onSelectSession,
  onSelectEntity,
  onNewPlan,
  onNewTodo,
  onNewSession,
  onNewBareSession,
  onMarkTodoDone,
  onMarkTodoUndone,
  onMoveSession,
  onUnbindSession,
  onRollup,
  isLoading = false,
}: GoalTreeViewProps) {
  // State for tree data
  const [goals, setGoals] = useState<GoalInfo[]>(initialGoals);
  const [plans, setPlans] = useState<Map<string, PlanInfo[]>>(new Map());
  const [todos, setTodos] = useState<Map<string, TodoInfo[]>>(new Map());
  const [boundSessions, setBoundSessions] = useState<Map<string, SessionBindingInfo[]>>(new Map());
  const [unboundSessions, setUnboundSessions] = useState<SessionBindingInfo[]>([]);
  const [goalProgress, setGoalProgress] = useState<Map<string, GoalProgress>>(new Map());
  const [stats, setStats] = useState<GoalTreeStats | undefined>(initialStats);

  // UI state
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [unboundExpanded, setUnboundExpanded] = useState(false);

  // Load initial data
  useEffect(() => {
    if (!goalsClient) return;

    const loadData = async () => {
      try {
        // Load root goals
        const rootGoals = await goalsClient.getRootGoals();
        setGoals(rootGoals);

        // Load stats
        const newStats = await goalsClient.getStats();
        setStats(newStats);

        // Load collapsed IDs
        const collapsedIds = await goalsClient.getCollapsedIds();
        // Initially expand all non-collapsed nodes
        const allIds = new Set<string>();
        rootGoals.forEach((g) => allIds.add(g.id));
        collapsedIds.forEach((id) => allIds.delete(id));
        setExpandedIds(allIds);

        // Load plans and sessions for each goal
        const newPlans = new Map<string, PlanInfo[]>();
        const newTodos = new Map<string, TodoInfo[]>();
        const newBoundSessions = new Map<string, SessionBindingInfo[]>();
        const newGoalProgress = new Map<string, GoalProgress>();

        for (const goal of rootGoals) {
          // Load plans for goal
          const goalPlans = await goalsClient.getPlansForGoal(goal.id);
          newPlans.set(goal.id, goalPlans);

          // Load progress for goal
          const progress = await goalsClient.getGoalProgress(goal.id);
          newGoalProgress.set(goal.id, progress);

          // Load sessions bound to goal
          const goalSessions = await goalsClient.getBoundSessions(goal.id);
          newBoundSessions.set(goal.id, goalSessions);

          // Load todos and sessions for each plan
          for (const plan of goalPlans) {
            const planTodos = await goalsClient.getTodosForPlan(plan.id);
            newTodos.set(plan.id, planTodos);

            const planSessions = await goalsClient.getBoundSessions(plan.id);
            newBoundSessions.set(plan.id, planSessions);

            // Load sessions for each todo
            for (const todo of planTodos) {
              const todoSessions = await goalsClient.getBoundSessions(todo.id);
              newBoundSessions.set(todo.id, todoSessions);
            }
          }
        }

        setPlans(newPlans);
        setTodos(newTodos);
        setBoundSessions(newBoundSessions);
        setGoalProgress(newGoalProgress);

        // Load unbound sessions
        const unbound = await goalsClient.getUnboundSessions();
        setUnboundSessions(unbound);
      } catch (error) {
        console.error('Failed to load goal tree data:', error);
      }
    };

    loadData();
  }, [goalsClient]);

  // Subscribe to events
  useEffect(() => {
    if (!goalsClient) return;

    const unsubscribers: (() => void)[] = [];

    // Full rebuild event
    unsubscribers.push(
      goalsClient.onFullRebuild(() => {
        // Re-fetch all data
        goalsClient.getRootGoals().then(setGoals);
        goalsClient.getUnboundSessions().then(setUnboundSessions);
        goalsClient.getStats().then(setStats);
      })
    );

    // Goal events
    unsubscribers.push(
      goalsClient.onGoalAdded((data: GoalTreeEventData) => {
        if (data.entityId) {
          goalsClient.getGoal(data.entityId).then((goal) => {
            if (goal && !goal.parentGoalId) {
              setGoals((prev) => [...prev.filter((g) => g.id !== goal.id), goal]);
            }
          });
        }
      })
    );

    unsubscribers.push(
      goalsClient.onGoalUpdated((data: GoalTreeEventData) => {
        if (data.entityId) {
          goalsClient.getGoal(data.entityId).then((goal) => {
            if (goal) {
              setGoals((prev) => prev.map((g) => (g.id === goal.id ? goal : g)));
              goalsClient.getGoalProgress(goal.id).then((progress) => {
                setGoalProgress((prev) => new Map(prev).set(goal.id, progress));
              });
            }
          });
        }
      })
    );

    unsubscribers.push(
      goalsClient.onGoalRemoved((data: GoalTreeEventData) => {
        if (data.entityId) {
          setGoals((prev) => prev.filter((g) => g.id !== data.entityId));
        }
      })
    );

    // Plan events
    unsubscribers.push(
      goalsClient.onPlanAdded((data: GoalTreeEventData) => {
        if (data.entityId && data.data?.goalId) {
          const goalId = data.data.goalId as string;
          goalsClient.getPlansForGoal(goalId).then((goalPlans) => {
            setPlans((prev) => new Map(prev).set(goalId, goalPlans));
          });
        }
      })
    );

    unsubscribers.push(
      goalsClient.onPlanUpdated((data: GoalTreeEventData) => {
        if (data.entityId) {
          goalsClient.getPlan(data.entityId).then((plan) => {
            if (plan) {
              setPlans((prev) => {
                const newPlans = new Map(prev);
                const goalPlans = newPlans.get(plan.goalId) || [];
                newPlans.set(
                  plan.goalId,
                  goalPlans.map((p) => (p.id === plan.id ? plan : p))
                );
                return newPlans;
              });
            }
          });
        }
      })
    );

    // Todo events
    unsubscribers.push(
      goalsClient.onTodoAdded((data: GoalTreeEventData) => {
        if (data.entityId && data.data?.planIds) {
          const planIds = data.data.planIds as string[];
          planIds.forEach((planId) => {
            goalsClient.getTodosForPlan(planId).then((planTodos) => {
              setTodos((prev) => new Map(prev).set(planId, planTodos));
            });
          });
        }
      })
    );

    unsubscribers.push(
      goalsClient.onTodoUpdated((data: GoalTreeEventData) => {
        if (data.entityId) {
          goalsClient.getTodo(data.entityId).then((todo) => {
            if (todo && todo.planIds && todo.planIds.length > 0) {
              const planId = todo.planIds[0] as string;
              if (planId) {
                goalsClient.getTodosForPlan(planId).then((planTodos) => {
                  setTodos((prev) => new Map(prev).set(planId, planTodos));
                });
              }
            }
          });
        }
      })
    );

    unsubscribers.push(
      goalsClient.onTodoRemoved((data: GoalTreeEventData) => {
        if (data.entityId && data.data?.planIds) {
          const planIds = data.data.planIds as string[];
          planIds.forEach((planId) => {
            goalsClient.getTodosForPlan(planId).then((planTodos) => {
              setTodos((prev) => new Map(prev).set(planId, planTodos));
            });
          });
        }
      })
    );

    // Session events
    unsubscribers.push(
      goalsClient.onSessionBound((data: GoalTreeEventData) => {
        if (data.entityId) {
          goalsClient.getBoundSessions(data.entityId).then((sessions) => {
            setBoundSessions((prev) => new Map(prev).set(data.entityId!, sessions));
          });
        }
        goalsClient.getUnboundSessions().then(setUnboundSessions);
      })
    );

    unsubscribers.push(
      goalsClient.onSessionUnbound((data: GoalTreeEventData) => {
        if (data.entityId) {
          goalsClient.getBoundSessions(data.entityId).then((sessions) => {
            setBoundSessions((prev) => new Map(prev).set(data.entityId!, sessions));
          });
        }
        goalsClient.getUnboundSessions().then(setUnboundSessions);
      })
    );

    unsubscribers.push(
      goalsClient.onSessionUpdated((data: GoalTreeEventData) => {
        // Refresh sessions - we don't know which entity it belongs to
        goalsClient.getUnboundSessions().then(setUnboundSessions);
      })
    );

    return () => {
      unsubscribers.forEach((unsub) => unsub());
    };
  }, [goalsClient]);

  // Toggle expand/collapse
  const handleToggle = useCallback(
    (id: string) => {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) {
          next.delete(id);
          goalsClient?.setCollapsed(id, true);
        } else {
          next.add(id);
          goalsClient?.setCollapsed(id, false);
        }
        return next;
      });
    },
    [goalsClient]
  );

  // Handle entity selection
  const handleSelect = useCallback(
    (type: string, id: string) => {
      onSelectEntity?.(type, id);
      goalsClient?.selectEntity(type, id);
    },
    [onSelectEntity, goalsClient]
  );

  // Recursive render function for goal nodes
  const renderGoalNode = useCallback(
    (
      goal: GoalInfo,
      data: {
        progress: GoalProgress;
        plans: PlanInfo[];
        planTodos: Map<string, TodoInfo[]>;
        planSessions: Map<string, SessionBindingInfo[]>;
        todoSessions: Map<string, SessionBindingInfo[]>;
        goalSessions: SessionBindingInfo[];
        childGoals: GoalInfo[];
      }
    ): React.ReactNode => {
      // Build child goal data recursively
      const childGoalData = new Map<string, typeof data>();
      for (const childGoal of data.childGoals) {
        const childPlans = plans.get(childGoal.id) || [];
        const childPlanTodos = new Map<string, TodoInfo[]>();
        const childPlanSessions = new Map<string, SessionBindingInfo[]>();
        const childTodoSessions = new Map<string, SessionBindingInfo[]>();

        for (const plan of childPlans) {
          childPlanTodos.set(plan.id, todos.get(plan.id) || []);
          childPlanSessions.set(plan.id, boundSessions.get(plan.id) || []);
          for (const todo of childPlanTodos.get(plan.id) || []) {
            childTodoSessions.set(todo.id, boundSessions.get(todo.id) || []);
          }
        }

        childGoalData.set(childGoal.id, {
          progress: goalProgress.get(childGoal.id) || { completed: 0, total: 0 },
          plans: childPlans,
          planTodos: childPlanTodos,
          planSessions: childPlanSessions,
          todoSessions: childTodoSessions,
          goalSessions: boundSessions.get(childGoal.id) || [],
          childGoals: [], // TODO: Load nested child goals recursively
        });
      }

      return (
        <GoalNode
          key={goal.id}
          goal={goal}
          progress={data.progress}
          plans={data.plans}
          planTodos={data.planTodos}
          planSessions={data.planSessions}
          todoSessions={data.todoSessions}
          goalSessions={data.goalSessions}
          childGoals={data.childGoals}
          childGoalData={childGoalData}
          expandedIds={expandedIds}
          onToggle={handleToggle}
          onSelect={handleSelect}
          onNewPlan={onNewPlan ? () => onNewPlan(goal.id) : undefined}
          onNewSession={onNewSession ? () => onNewSession('goal', goal.id) : undefined}
          onRollup={onRollup ? () => onRollup('goal', goal.id) : undefined}
          onNewTodo={onNewTodo}
          onNewPlanSession={onNewSession ? (planId: string) => onNewSession('plan', planId) : undefined}
          onPlanRollup={onRollup ? (planId: string) => onRollup('plan', planId) : undefined}
          onMarkTodoDone={onMarkTodoDone}
          onMarkTodoUndone={onMarkTodoUndone}
          onNewTodoSession={onNewSession ? (todoId: string) => onNewSession('todo', todoId) : undefined}
          onSelectSession={onSelectSession || (() => {})}
          onMoveSession={onMoveSession}
          onUnbindSession={onUnbindSession}
          hoveredNodeId={hoveredNodeId}
          setHoveredNodeId={setHoveredNodeId}
          renderGoalNode={renderGoalNode}
        />
      );
    },
    [
      plans,
      todos,
      boundSessions,
      goalProgress,
      expandedIds,
      handleToggle,
      handleSelect,
      onNewPlan,
      onNewTodo,
      onNewSession,
      onMarkTodoDone,
      onMarkTodoUndone,
      onMoveSession,
      onUnbindSession,
      onRollup,
      onSelectSession,
      hoveredNodeId,
    ]
  );

  // Build tree data for each goal
  const goalData = useMemo(() => {
    const data = new Map<
      string,
      {
        progress: GoalProgress;
        plans: PlanInfo[];
        planTodos: Map<string, TodoInfo[]>;
        planSessions: Map<string, SessionBindingInfo[]>;
        todoSessions: Map<string, SessionBindingInfo[]>;
        goalSessions: SessionBindingInfo[];
        childGoals: GoalInfo[];
      }
    >();

    for (const goal of goals) {
      const goalPlans = plans.get(goal.id) || [];
      const planTodos = new Map<string, TodoInfo[]>();
      const planSessions = new Map<string, SessionBindingInfo[]>();
      const todoSessions = new Map<string, SessionBindingInfo[]>();

      for (const plan of goalPlans) {
        planTodos.set(plan.id, todos.get(plan.id) || []);
        planSessions.set(plan.id, boundSessions.get(plan.id) || []);

        for (const todo of planTodos.get(plan.id) || []) {
          todoSessions.set(todo.id, boundSessions.get(todo.id) || []);
        }
      }

      data.set(goal.id, {
        progress: goalProgress.get(goal.id) || { completed: 0, total: 0 },
        plans: goalPlans,
        planTodos,
        planSessions,
        todoSessions,
        goalSessions: boundSessions.get(goal.id) || [],
        childGoals: goal.childGoalIds?.map((id) => goals.find((g) => g.id === id)).filter(Boolean) as GoalInfo[] || [],
      });
    }

    return data;
  }, [goals, plans, todos, boundSessions, goalProgress]);

  // Render loading state
  if (isLoading) {
    return <div className="goal-tree-view goal-tree-view--empty">Loading goals...</div>;
  }

  // Render empty state
  if (goals.length === 0 && unboundSessions.length === 0) {
    return <div className="goal-tree-view goal-tree-view--empty">No goals</div>;
  }

  // Root label with stats
  const rootLabel = stats
    ? `Goals (${stats.activeGoals}g, ${stats.pendingTodos}+${stats.inProgressTodos}t)`
    : 'Goals';

  return (
    <div className="goal-tree-view">
      <div className="goal-tree-header">
        <span className="goal-tree-header__label">{rootLabel}</span>
        {onNewBareSession && (
          <button
            className="goal-tree-header__new-session"
            onClick={onNewBareSession}
            title="Start new session"
          >
            + New
          </button>
        )}
      </div>
      <ul className="goal-tree-root">
        {goals.map((goal) => {
          const data = goalData.get(goal.id);
          if (!data) return null;
          return renderGoalNode(goal, data);
        })}

        <UnboundSection
          sessions={unboundSessions}
          isExpanded={unboundExpanded}
          onToggle={() => setUnboundExpanded(!unboundExpanded)}
          onSelectSession={onSelectSession || (() => {})}
          onMoveSession={onMoveSession}
          hoveredNodeId={hoveredNodeId}
          setHoveredNodeId={setHoveredNodeId}
        />
      </ul>
    </div>
  );
});

export default GoalTreeView;
