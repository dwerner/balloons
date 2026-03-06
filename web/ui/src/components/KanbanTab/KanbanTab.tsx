/**
 * KanbanTab - Kanban board management interface
 *
 * General subtab provides:
 * - Board list with create/delete
 * - Board view with columns and tasks
 * - Desktop: Horizontal columns with drag-and-drop
 * - Mobile: Accordion layout with move-to-column modal
 * - Real-time updates via WebSocket subscriptions
 *
 * URL ROUTING INTEGRATION:
 * - Board selection should update URL to #/kanban/:boardId
 * - Task selection/focus could use #/kanban/:boardId/task/:taskId
 * - See docs/url-routing.md for the full routing design
 */

import React, { useState, useEffect, useCallback, memo } from 'react';
import type {
  BoardInfo,
  BoardStateInfo,
  KanbanTaskInfo,
  ColumnInfo,
  KanbanWebSocketServiceClient,
} from '../../../../generated/balloons-client';
import { useLayout } from '../layout';
import './KanbanTab.css';

// =============================================================================
// Helper Components
// =============================================================================

/** Status indicator for board connection state */
function ConnectionStatus({ connected }: { connected: boolean }) {
  return (
    <span
      className={`kanban-connection-status ${connected ? 'kanban-connection-status--connected' : ''}`}
      title={connected ? 'Connected' : 'Disconnected'}
    >
      {connected ? '●' : '○'}
    </span>
  );
}

/** Task card displayed within a column (desktop - draggable) */
const TaskCardDesktop = memo(function TaskCardDesktop({
  task,
  onEdit,
  onDelete,
  isDragging,
  onDragStart,
  onDragEnd,
}: {
  task: KanbanTaskInfo;
  onEdit: (task: KanbanTaskInfo) => void;
  onDelete: (taskId: string) => void;
  isDragging?: boolean;
  onDragStart: (e: React.DragEvent, task: KanbanTaskInfo) => void;
  onDragEnd: (e: React.DragEvent) => void;
}) {
  return (
    <div
      className={`kanban-task-card ${isDragging ? 'kanban-task-card--dragging' : ''}`}
      draggable
      onDragStart={(e) => onDragStart(e, task)}
      onDragEnd={onDragEnd}
    >
      <div className="kanban-task-card__title">{task.title}</div>
      {task.description && (
        <div className="kanban-task-card__description">{task.description}</div>
      )}
      <div className="kanban-task-card__actions">
        <button
          className="kanban-task-card__action"
          onClick={(e) => {
            e.stopPropagation();
            onEdit(task);
          }}
          title="Edit task"
        >
          ✎
        </button>
        <button
          className="kanban-task-card__action kanban-task-card__action--danger"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(task.id);
          }}
          title="Delete task"
        >
          ×
        </button>
      </div>
    </div>
  );
});

/** Task card for mobile - with Move button */
const TaskCardMobile = memo(function TaskCardMobile({
  task,
  onEdit,
  onDelete,
  onMove,
}: {
  task: KanbanTaskInfo;
  onEdit: (task: KanbanTaskInfo) => void;
  onDelete: (taskId: string) => void;
  onMove: (task: KanbanTaskInfo) => void;
}) {
  return (
    <div className="kanban-task-card kanban-task-card--mobile">
      <div className="kanban-task-card__content">
        <div className="kanban-task-card__title">{task.title}</div>
        {task.description && (
          <div className="kanban-task-card__description">{task.description}</div>
        )}
      </div>
      <div className="kanban-task-card__actions kanban-task-card__actions--mobile">
        <button
          className="kanban-task-card__action"
          onClick={(e) => {
            e.stopPropagation();
            onMove(task);
          }}
          title="Move task"
        >
          ↔
        </button>
        <button
          className="kanban-task-card__action"
          onClick={(e) => {
            e.stopPropagation();
            onEdit(task);
          }}
          title="Edit task"
        >
          ✎
        </button>
        <button
          className="kanban-task-card__action kanban-task-card__action--danger"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(task.id);
          }}
          title="Delete task"
        >
          ×
        </button>
      </div>
    </div>
  );
});

/** Column header with add task button */
const ColumnHeader = memo(function ColumnHeader({
  column,
  taskCount,
  onAddTask,
}: {
  column: ColumnInfo;
  taskCount: number;
  onAddTask: () => void;
}) {
  return (
    <div className="kanban-column__header">
      <span className="kanban-column__title">{column.name}</span>
      <span className="kanban-column__count">{taskCount}</span>
      <button
        className="kanban-column__add-btn"
        onClick={onAddTask}
        title="Add task to this column"
      >
        +
      </button>
    </div>
  );
});

/** Kanban column for desktop - horizontal layout with drag-drop */
const KanbanColumnDesktop = memo(function KanbanColumnDesktop({
  column,
  tasks,
  onAddTask,
  onEditTask,
  onDeleteTask,
  onDragStart,
  onDragEnd,
  onDragOver,
  onDrop,
  dragOverColumnId,
}: {
  column: ColumnInfo;
  tasks: KanbanTaskInfo[];
  onAddTask: (columnId: string) => void;
  onEditTask: (task: KanbanTaskInfo) => void;
  onDeleteTask: (taskId: string) => void;
  onDragStart: (e: React.DragEvent, task: KanbanTaskInfo, columnId: string) => void;
  onDragEnd: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent, columnId: string) => void;
  onDrop: (e: React.DragEvent, columnId: string) => void;
  dragOverColumnId: string | null;
}) {
  const columnTasks = (column.taskIds || [])
    .map(id => tasks.find(t => t.id === id))
    .filter((t): t is KanbanTaskInfo => t !== undefined);

  const isDropTarget = dragOverColumnId === column.id;

  return (
    <div
      className={`kanban-column ${isDropTarget ? 'kanban-column--drop-target' : ''}`}
      onDragOver={(e) => onDragOver(e, column.id)}
      onDrop={(e) => onDrop(e, column.id)}
    >
      <ColumnHeader
        column={column}
        taskCount={columnTasks.length}
        onAddTask={() => onAddTask(column.id)}
      />
      <div className="kanban-column__tasks">
        {columnTasks.map((task) => (
          <TaskCardDesktop
            key={task.id}
            task={task}
            onEdit={onEditTask}
            onDelete={onDeleteTask}
            onDragStart={(e, t) => onDragStart(e, t, column.id)}
            onDragEnd={onDragEnd}
          />
        ))}
        {columnTasks.length === 0 && (
          <div className="kanban-column__empty">
            Drop tasks here
          </div>
        )}
      </div>
    </div>
  );
});

/** Accordion column for mobile - collapsible with tap-to-expand */
const AccordionColumn = memo(function AccordionColumn({
  column,
  tasks,
  isExpanded,
  onToggle,
  onAddTask,
  onEditTask,
  onDeleteTask,
  onMoveTask,
}: {
  column: ColumnInfo;
  tasks: KanbanTaskInfo[];
  isExpanded: boolean;
  onToggle: () => void;
  onAddTask: (columnId: string) => void;
  onEditTask: (task: KanbanTaskInfo) => void;
  onDeleteTask: (taskId: string) => void;
  onMoveTask: (task: KanbanTaskInfo, fromColumnId: string) => void;
}) {
  const columnTasks = (column.taskIds || [])
    .map(id => tasks.find(t => t.id === id))
    .filter((t): t is KanbanTaskInfo => t !== undefined);

  return (
    <div className={`kanban-accordion ${isExpanded ? 'kanban-accordion--expanded' : ''}`}>
      <button
        className="kanban-accordion__header"
        onClick={onToggle}
        type="button"
      >
        <span className="kanban-accordion__icon">
          {isExpanded ? '▼' : '▶'}
        </span>
        <span className="kanban-accordion__title">{column.name}</span>
        <span className="kanban-accordion__count">{columnTasks.length}</span>
        <button
          className="kanban-accordion__add-btn"
          onClick={(e) => {
            e.stopPropagation();
            onAddTask(column.id);
          }}
          title="Add task"
        >
          +
        </button>
      </button>
      {isExpanded && (
        <div className="kanban-accordion__content">
          {columnTasks.length === 0 ? (
            <div className="kanban-accordion__empty">No tasks in this column</div>
          ) : (
            columnTasks.map((task) => (
              <TaskCardMobile
                key={task.id}
                task={task}
                onEdit={onEditTask}
                onDelete={onDeleteTask}
                onMove={(t) => onMoveTask(t, column.id)}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
});

/** Move task modal for mobile */
function MoveTaskModal({
  task,
  columns,
  currentColumnId,
  onMove,
  onClose,
}: {
  task: KanbanTaskInfo;
  columns: ColumnInfo[];
  currentColumnId: string;
  onMove: (toColumnId: string) => void;
  onClose: () => void;
}) {
  return (
    <div className="kanban-modal-overlay" onClick={onClose}>
      <div className="kanban-modal kanban-modal--bottom-sheet" onClick={(e) => e.stopPropagation()}>
        <div className="kanban-modal__header">
          <h3>Move "{task.title}"</h3>
          <button className="kanban-modal__close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="kanban-modal__content">
          <div className="kanban-move-options">
            {columns
              .sort((a, b) => a.position - b.position)
              .map((col) => (
                <button
                  key={col.id}
                  className={`kanban-move-option ${col.id === currentColumnId ? 'kanban-move-option--current' : ''}`}
                  onClick={() => col.id !== currentColumnId && onMove(col.id)}
                  disabled={col.id === currentColumnId}
                >
                  <span className="kanban-move-option__name">{col.name}</span>
                  {col.id === currentColumnId && (
                    <span className="kanban-move-option__current">current</span>
                  )}
                </button>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Board View
// =============================================================================

export interface BoardViewProps {
  boardState: BoardStateInfo;
  kanbanClient: KanbanWebSocketServiceClient;
  clientId: string;
  /** Back button handler. If not provided, back button is not shown. */
  onBack?: () => void;
}

export function BoardView({ boardState, kanbanClient, clientId, onBack }: BoardViewProps) {
  const { layoutMode } = useLayout();
  const isMobile = layoutMode === 'mobile';

  const [localState, setLocalState] = useState<BoardStateInfo>(boardState);
  const [draggingTask, setDraggingTask] = useState<{ task: KanbanTaskInfo; fromColumnId: string } | null>(null);
  const [dragOverColumnId, setDragOverColumnId] = useState<string | null>(null);

  // Accordion state for mobile (which columns are expanded)
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(() => {
    // Default: expand the first column with tasks, or first column
    const firstWithTasks = boardState.columns.find(
      col => (col.taskIds || []).length > 0
    );
    const initialId = firstWithTasks?.id || boardState.columns[0]?.id;
    return new Set(initialId ? [initialId] : []);
  });

  // Task creation modal state
  const [showAddTask, setShowAddTask] = useState(false);
  const [addTaskColumnId, setAddTaskColumnId] = useState<string | null>(null);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskDescription, setNewTaskDescription] = useState('');

  // Task edit modal state
  const [editingTask, setEditingTask] = useState<KanbanTaskInfo | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');

  // Task move modal state (mobile)
  const [movingTask, setMovingTask] = useState<{ task: KanbanTaskInfo; fromColumnId: string } | null>(null);

  // Update local state when prop changes (e.g., from events)
  useEffect(() => {
    setLocalState(boardState);
  }, [boardState]);

  // Toggle accordion column expansion
  const toggleColumn = useCallback((columnId: string) => {
    setExpandedColumns((prev) => {
      const next = new Set(prev);
      if (next.has(columnId)) {
        next.delete(columnId);
      } else {
        next.add(columnId);
      }
      return next;
    });
  }, []);

  // Handle adding a task
  const handleAddTask = useCallback(async () => {
    if (!newTaskTitle.trim() || !addTaskColumnId) return;

    try {
      await kanbanClient.createTask(
        localState.board.id,
        newTaskTitle.trim(),
        newTaskDescription.trim() || undefined,
        addTaskColumnId
      );
      setShowAddTask(false);
      setNewTaskTitle('');
      setNewTaskDescription('');
      // Expand the column we just added to
      setExpandedColumns((prev) => new Set(prev).add(addTaskColumnId));
      setAddTaskColumnId(null);
    } catch (e) {
      console.error('Failed to create task:', e);
    }
  }, [kanbanClient, localState.board.id, addTaskColumnId, newTaskTitle, newTaskDescription]);

  // Handle editing a task
  const handleEditTask = useCallback(async () => {
    if (!editingTask || !editTitle.trim()) return;

    try {
      await kanbanClient.updateTask(
        editingTask.id,
        localState.board.id,
        editTitle.trim(),
        editDescription.trim() || undefined
      );
      setEditingTask(null);
      setEditTitle('');
      setEditDescription('');
    } catch (e) {
      console.error('Failed to update task:', e);
    }
  }, [kanbanClient, localState.board.id, editingTask, editTitle, editDescription]);

  // Handle deleting a task
  const handleDeleteTask = useCallback(async (taskId: string) => {
    try {
      await kanbanClient.deleteTask(taskId, localState.board.id);
    } catch (e) {
      console.error('Failed to delete task:', e);
    }
  }, [kanbanClient, localState.board.id]);

  // Handle moving a task (from move modal)
  const handleMoveTask = useCallback(async (toColumnId: string) => {
    if (!movingTask) return;

    const { task, fromColumnId } = movingTask;
    setMovingTask(null);

    if (fromColumnId === toColumnId) return;

    try {
      await kanbanClient.moveTask(
        task.id,
        localState.board.id,
        toColumnId,
        undefined,
        fromColumnId
      );
      // Expand the target column
      setExpandedColumns((prev) => new Set(prev).add(toColumnId));
    } catch (e) {
      console.error('Failed to move task:', e);
    }
  }, [kanbanClient, localState.board.id, movingTask]);

  // Desktop drag handlers
  const handleDragStart = useCallback((e: React.DragEvent, task: KanbanTaskInfo, fromColumnId: string) => {
    setDraggingTask({ task, fromColumnId });
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  const handleDragEnd = useCallback(() => {
    setDraggingTask(null);
    setDragOverColumnId(null);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, columnId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDragOverColumnId(columnId);
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent, toColumnId: string) => {
    e.preventDefault();
    setDragOverColumnId(null);

    if (!draggingTask) return;

    const { task, fromColumnId } = draggingTask;
    setDraggingTask(null);

    if (fromColumnId === toColumnId) return;

    try {
      await kanbanClient.moveTask(
        task.id,
        localState.board.id,
        toColumnId,
        undefined,
        fromColumnId
      );
    } catch (e) {
      console.error('Failed to move task:', e);
    }
  }, [kanbanClient, localState.board.id, draggingTask]);

  // Open add task modal for a specific column
  const openAddTask = useCallback((columnId: string) => {
    setAddTaskColumnId(columnId);
    setShowAddTask(true);
    setNewTaskTitle('');
    setNewTaskDescription('');
  }, []);

  // Open edit task modal
  const openEditTask = useCallback((task: KanbanTaskInfo) => {
    setEditingTask(task);
    setEditTitle(task.title);
    setEditDescription(task.description);
  }, []);

  // Open move modal for mobile
  const openMoveTask = useCallback((task: KanbanTaskInfo, fromColumnId: string) => {
    setMovingTask({ task, fromColumnId });
  }, []);

  const sortedColumns = localState.columns.sort((a, b) => a.position - b.position);

  return (
    <div className={`kanban-board-view ${isMobile ? 'kanban-board-view--mobile' : ''}`}>
      {/* Board header */}
      <div className="kanban-board-view__header">
        {onBack && (
          <button className="kanban-back-btn" onClick={onBack}>
            ← Back
          </button>
        )}
        <h3 className="kanban-board-view__title">{localState.board.name}</h3>
      </div>

      {/* Columns - desktop or mobile layout */}
      {isMobile ? (
        // Mobile: Accordion layout - whole area scrolls together
        <div className="kanban-accordion-container">
          {sortedColumns.map((column) => (
            <AccordionColumn
              key={column.id}
              column={column}
              tasks={localState.tasks}
              isExpanded={expandedColumns.has(column.id)}
              onToggle={() => toggleColumn(column.id)}
              onAddTask={openAddTask}
              onEditTask={openEditTask}
              onDeleteTask={handleDeleteTask}
              onMoveTask={openMoveTask}
            />
          ))}
        </div>
      ) : (
        // Desktop: Horizontal columns
        <div className="kanban-columns-container">
          {sortedColumns.map((column) => (
            <KanbanColumnDesktop
              key={column.id}
              column={column}
              tasks={localState.tasks}
              onAddTask={openAddTask}
              onEditTask={openEditTask}
              onDeleteTask={handleDeleteTask}
              onDragStart={handleDragStart}
              onDragEnd={handleDragEnd}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              dragOverColumnId={dragOverColumnId}
            />
          ))}
        </div>
      )}

      {/* Add Task Modal */}
      {showAddTask && (
        <div className="kanban-modal-overlay" onClick={() => setShowAddTask(false)}>
          <div className="kanban-modal" onClick={(e) => e.stopPropagation()}>
            <div className="kanban-modal__header">
              <h3>Add Task</h3>
              <button className="kanban-modal__close" onClick={() => setShowAddTask(false)}>
                ×
              </button>
            </div>
            <div className="kanban-modal__content">
              <div className="kanban-form-field">
                <label>Title</label>
                <input
                  type="text"
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder="Task title"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleAddTask()}
                />
              </div>
              <div className="kanban-form-field">
                <label>Description (optional)</label>
                <textarea
                  value={newTaskDescription}
                  onChange={(e) => setNewTaskDescription(e.target.value)}
                  placeholder="Task description"
                  rows={3}
                />
              </div>
            </div>
            <div className="kanban-modal__actions">
              <button className="kanban-btn" onClick={() => setShowAddTask(false)}>
                Cancel
              </button>
              <button
                className="kanban-btn kanban-btn--primary"
                onClick={handleAddTask}
                disabled={!newTaskTitle.trim()}
              >
                Add Task
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Task Modal */}
      {editingTask && (
        <div className="kanban-modal-overlay" onClick={() => setEditingTask(null)}>
          <div className="kanban-modal" onClick={(e) => e.stopPropagation()}>
            <div className="kanban-modal__header">
              <h3>Edit Task</h3>
              <button className="kanban-modal__close" onClick={() => setEditingTask(null)}>
                ×
              </button>
            </div>
            <div className="kanban-modal__content">
              <div className="kanban-form-field">
                <label>Title</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  placeholder="Task title"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleEditTask()}
                />
              </div>
              <div className="kanban-form-field">
                <label>Description</label>
                <textarea
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  placeholder="Task description"
                  rows={3}
                />
              </div>
            </div>
            <div className="kanban-modal__actions">
              <button className="kanban-btn" onClick={() => setEditingTask(null)}>
                Cancel
              </button>
              <button
                className="kanban-btn kanban-btn--primary"
                onClick={handleEditTask}
                disabled={!editTitle.trim()}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Move Task Modal (mobile) */}
      {movingTask && (
        <MoveTaskModal
          task={movingTask.task}
          columns={localState.columns}
          currentColumnId={movingTask.fromColumnId}
          onMove={handleMoveTask}
          onClose={() => setMovingTask(null)}
        />
      )}
    </div>
  );
}

// =============================================================================
// Board List
// =============================================================================

interface BoardListProps {
  boards: BoardInfo[];
  onSelectBoard: (boardId: string) => void;
  onCreateBoard: (name: string) => void;
  onDeleteBoard: (boardId: string) => void;
  isLoading: boolean;
}

function BoardList({
  boards,
  onSelectBoard,
  onCreateBoard,
  onDeleteBoard,
  isLoading,
}: BoardListProps) {
  const [showCreate, setShowCreate] = useState(false);
  const [newBoardName, setNewBoardName] = useState('');

  const handleCreate = useCallback(() => {
    if (!newBoardName.trim()) return;
    onCreateBoard(newBoardName.trim());
    setNewBoardName('');
    setShowCreate(false);
  }, [newBoardName, onCreateBoard]);

  if (isLoading) {
    return (
      <div className="kanban-board-list kanban-board-list--loading">
        Loading boards...
      </div>
    );
  }

  return (
    <div className="kanban-board-list">
      <div className="kanban-board-list__header">
        <h3>Boards</h3>
        <button
          className="kanban-btn kanban-btn--primary"
          onClick={() => setShowCreate(true)}
        >
          + New Board
        </button>
      </div>

      {boards.length === 0 ? (
        <div className="kanban-board-list__empty">
          No boards yet. Create one to get started!
        </div>
      ) : (
        <div className="kanban-board-list__items">
          {boards.map((board) => (
            <div
              key={board.id}
              className="kanban-board-list__item"
              onClick={() => onSelectBoard(board.id)}
            >
              <div className="kanban-board-list__item-info">
                <span className="kanban-board-list__item-name">{board.name}</span>
                <span className="kanban-board-list__item-date">
                  Created: {new Date(board.createdAt).toLocaleDateString()}
                </span>
              </div>
              <button
                className="kanban-board-list__item-delete"
                onClick={(e) => {
                  e.stopPropagation();
                  if (confirm(`Delete board "${board.name}"?`)) {
                    onDeleteBoard(board.id);
                  }
                }}
                title="Delete board"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Create Board Modal */}
      {showCreate && (
        <div className="kanban-modal-overlay" onClick={() => setShowCreate(false)}>
          <div className="kanban-modal" onClick={(e) => e.stopPropagation()}>
            <div className="kanban-modal__header">
              <h3>Create Board</h3>
              <button className="kanban-modal__close" onClick={() => setShowCreate(false)}>
                ×
              </button>
            </div>
            <div className="kanban-modal__content">
              <div className="kanban-form-field">
                <label>Board Name</label>
                <input
                  type="text"
                  value={newBoardName}
                  onChange={(e) => setNewBoardName(e.target.value)}
                  placeholder="My Project Board"
                  autoFocus
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
              </div>
            </div>
            <div className="kanban-modal__actions">
              <button className="kanban-btn" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button
                className="kanban-btn kanban-btn--primary"
                onClick={handleCreate}
                disabled={!newBoardName.trim()}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Main KanbanTab Component
// =============================================================================

export interface KanbanTabProps {
  /** Kanban service client */
  kanbanClient?: KanbanWebSocketServiceClient;
  /** Client ID for subscriptions */
  clientId?: string;
  /** Whether connected to server */
  isConnected: boolean;
}

export const KanbanTab = memo(function KanbanTab({
  kanbanClient,
  clientId,
  isConnected,
}: KanbanTabProps) {
  // Board list state
  const [boards, setBoards] = useState<BoardInfo[]>([]);
  const [isLoadingBoards, setIsLoadingBoards] = useState(true);

  // Selected board state
  const [selectedBoardId, setSelectedBoardId] = useState<string | null>(null);
  const [boardState, setBoardState] = useState<BoardStateInfo | null>(null);
  const [isLoadingBoard, setIsLoadingBoard] = useState(false);

  // Error state
  const [error, setError] = useState<string | null>(null);

  // Load board list on mount
  useEffect(() => {
    if (!kanbanClient || !isConnected) return;

    const loadBoards = async () => {
      try {
        setIsLoadingBoards(true);
        const boardList = await kanbanClient.listBoards();
        setBoards(boardList);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load boards');
      } finally {
        setIsLoadingBoards(false);
      }
    };

    loadBoards();
  }, [kanbanClient, isConnected]);

  // Subscribe to board events
  useEffect(() => {
    if (!kanbanClient) return;

    const unsubBoardCreated = kanbanClient.boardCreated((event) => {
      setBoards((prev) => [...prev, event.board.board]);
    });

    const unsubBoardDeleted = kanbanClient.boardDeleted((event) => {
      setBoards((prev) => prev.filter((b) => b.id !== event.boardId));
      // Clear selection if the deleted board was selected
      if (selectedBoardId === event.boardId) {
        setSelectedBoardId(null);
        setBoardState(null);
      }
    });

    return () => {
      unsubBoardCreated();
      unsubBoardDeleted();
    };
  }, [kanbanClient, selectedBoardId]);

  // Subscribe to selected board
  useEffect(() => {
    if (!kanbanClient || !clientId || !selectedBoardId) return;

    let cancelled = false;

    const subscribeToBoard = async () => {
      try {
        setIsLoadingBoard(true);
        const result = await kanbanClient.subscribeBoard(selectedBoardId, clientId);
        if (cancelled) return;

        if (result.subscribed && result.board) {
          setBoardState(result.board);
          setError(null);
        } else {
          setError(result.error || 'Failed to subscribe to board');
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load board');
        }
      } finally {
        if (!cancelled) {
          setIsLoadingBoard(false);
        }
      }
    };

    subscribeToBoard();

    // Subscribe to board-specific events
    const unsubTaskCreated = kanbanClient.taskCreated((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        // Add task to tasks list
        const newTasks = [...prev.tasks, event.task];
        // Add task ID to column
        const newColumns = prev.columns.map((col) => {
          if (col.id === event.columnId) {
            return { ...col, taskIds: [...(col.taskIds || []), event.task.id] };
          }
          return col;
        });
        return { ...prev, tasks: newTasks, columns: newColumns };
      });
    });

    const unsubTaskUpdated = kanbanClient.taskUpdated((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        const newTasks = prev.tasks.map((t) =>
          t.id === event.task.id ? event.task : t
        );
        return { ...prev, tasks: newTasks };
      });
    });

    const unsubTaskDeleted = kanbanClient.taskDeleted((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        // Remove task from tasks list
        const newTasks = prev.tasks.filter((t) => t.id !== event.taskId);
        // Remove task ID from columns
        const newColumns = prev.columns.map((col) => ({
          ...col,
          taskIds: (col.taskIds || []).filter((id) => id !== event.taskId),
        }));
        return { ...prev, tasks: newTasks, columns: newColumns };
      });
    });

    const unsubTaskMoved = kanbanClient.taskMoved((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        // Move task between columns
        const newColumns = prev.columns.map((col) => {
          if (col.id === event.fromColumnId) {
            return {
              ...col,
              taskIds: (col.taskIds || []).filter((id) => id !== event.taskId),
            };
          }
          if (col.id === event.toColumnId) {
            const newTaskIds = [...(col.taskIds || [])];
            newTaskIds.splice(event.newPosition, 0, event.taskId);
            return { ...col, taskIds: newTaskIds };
          }
          return col;
        });
        return { ...prev, columns: newColumns };
      });
    });

    const unsubTasksReordered = kanbanClient.tasksReordered((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        const newColumns = prev.columns.map((col) => {
          if (col.id === event.columnId) {
            return { ...col, taskIds: event.taskIds };
          }
          return col;
        });
        return { ...prev, columns: newColumns };
      });
    });

    const unsubColumnAdded = kanbanClient.columnAdded((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        return { ...prev, columns: [...prev.columns, event.column] };
      });
    });

    const unsubColumnDeleted = kanbanClient.columnDeleted((event) => {
      if (event.boardId !== selectedBoardId) return;
      setBoardState((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          columns: prev.columns.filter((c) => c.id !== event.columnId),
        };
      });
    });

    return () => {
      cancelled = true;
      unsubTaskCreated();
      unsubTaskUpdated();
      unsubTaskDeleted();
      unsubTaskMoved();
      unsubTasksReordered();
      unsubColumnAdded();
      unsubColumnDeleted();

      // Unsubscribe from board
      if (kanbanClient && clientId) {
        kanbanClient.unsubscribeBoard(selectedBoardId, clientId).catch(() => {});
      }
    };
  }, [kanbanClient, clientId, selectedBoardId]);

  // Handlers
  const handleCreateBoard = useCallback(async (name: string) => {
    if (!kanbanClient) return;
    try {
      await kanbanClient.createBoard(name);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create board');
    }
  }, [kanbanClient]);

  const handleDeleteBoard = useCallback(async (boardId: string) => {
    if (!kanbanClient) return;
    try {
      await kanbanClient.deleteBoard(boardId);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete board');
    }
  }, [kanbanClient]);

  const handleSelectBoard = useCallback((boardId: string) => {
    setSelectedBoardId(boardId);
    setBoardState(null);
  }, []);

  const handleBackToList = useCallback(() => {
    setSelectedBoardId(null);
    setBoardState(null);
  }, []);

  // Not connected state
  if (!isConnected) {
    return (
      <div className="kanban-tab">
        <div className="kanban-tab__disconnected">
          <ConnectionStatus connected={false} />
          <span>Connect to server to manage kanban boards</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="kanban-tab">
        <div className="kanban-tab__error">
          <span className="kanban-tab__error-icon">⚠️</span>
          <span>{error}</span>
          <button
            className="kanban-btn"
            onClick={() => {
              setError(null);
              setSelectedBoardId(null);
            }}
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  // Loading selected board
  if (selectedBoardId && isLoadingBoard) {
    return (
      <div className="kanban-tab kanban-tab--loading">
        Loading board...
      </div>
    );
  }

  // Board view
  if (selectedBoardId && boardState && kanbanClient && clientId) {
    return (
      <div className="kanban-tab">
        <BoardView
          boardState={boardState}
          kanbanClient={kanbanClient}
          clientId={clientId}
          onBack={handleBackToList}
        />
      </div>
    );
  }

  // Board list
  return (
    <div className="kanban-tab">
      <BoardList
        boards={boards}
        onSelectBoard={handleSelectBoard}
        onCreateBoard={handleCreateBoard}
        onDeleteBoard={handleDeleteBoard}
        isLoading={isLoadingBoards}
      />
    </div>
  );
});

export default KanbanTab;
