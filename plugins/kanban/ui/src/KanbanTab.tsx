/**
 * KanbanTab - Interactive kanban board for task management
 *
 * Features:
 * - Vertical accordion layout (space-efficient for sidebar)
 * - Collapsible columns with expand/collapse
 * - Create, update, delete tasks
 * - Real-time updates from kanban domain events
 * - Drag and drop within expanded columns
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Board, Task, Column, PluginContext, DomainEventData, DragState } from './types';
import './KanbanTab.css';

// Re-export types
export type { PluginContext, DomainEventData };

export function KanbanTab({
  sendMessage,
  sessionId,
  subscribeToDomainEvents,
  requestDomainState,
  isLLMResponding = false,
  callDomainMethod,
  confirm,
}: PluginContext) {
  const [boards, setBoards] = useState<Board[]>([]);
  const [allBoards, setAllBoards] = useState<Board[]>([]);
  const [activeBoardId, setActiveBoardId] = useState<string | null>(null);
  const [expandedColumns, setExpandedColumns] = useState<Set<string>>(new Set());
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [dropTargetColumn, setDropTargetColumn] = useState<string | null>(null);
  const [isCreatingTask, setIsCreatingTask] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskColumn, setNewTaskColumn] = useState<string | null>(null);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [editForm, setEditForm] = useState({ title: '', description: '', resolution: '' });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showBoardForm, setShowBoardForm] = useState(false);
  const [showBoardPicker, setShowBoardPicker] = useState(false);
  const [newBoardName, setNewBoardName] = useState('');
  const [isLoadingAllBoards, setIsLoadingAllBoards] = useState(false);
  const [showBoardList, setShowBoardList] = useState(false);

  const activeBoard = useMemo(() => {
    return boards.find(b => b.id === activeBoardId) || boards[0] || null;
  }, [boards, activeBoardId]);

  // Initialize expanded columns - expand all columns that have items
  useEffect(() => {
    if (activeBoard) {
      // Find all columns with tasks
      const columnsWithTasks = activeBoard.columns
        .filter(c => c.taskIds.length > 0)
        .map(c => c.id);

      if (columnsWithTasks.length > 0) {
        setExpandedColumns(new Set(columnsWithTasks));
      } else if (activeBoard.columns.length > 0 && expandedColumns.size === 0) {
        // If no columns have tasks, expand "In Progress" or first column
        const inProgressCol = activeBoard.columns.find(c =>
          c.name.toLowerCase().includes('progress') || c.name.toLowerCase() === 'in progress'
        );
        setExpandedColumns(new Set([inProgressCol?.id || activeBoard.columns[0].id]));
      }
    }
  }, [activeBoard?.id]); // Only re-run when board changes, not on every task update

  // Subscribe to domain events
  useEffect(() => {
    if (!subscribeToDomainEvents || !sessionId) return;

    console.log('[KanbanTab] Subscribing to domain events for session:', sessionId);

    const unsubscribe = subscribeToDomainEvents('kanban', (event) => {
      console.log('[KanbanTab] Received domain event:', event);
      const data = event.data;

      switch (event.eventType) {
        case 'board_created': {
          const board = data.board as Board;
          console.log('[KanbanTab] Board created:', board.id);
          setBoards(prev => {
            if (prev.some(b => b.id === board.id)) {
              return prev.map(b => b.id === board.id ? board : b);
            }
            return [...prev, board];
          });
          setActiveBoardId(board.id);
          break;
        }

        case 'board_deleted': {
          const boardId = data.boardId as string || data.board_id as string;
          console.log('[KanbanTab] Board deleted:', boardId);
          setBoards(prev => prev.filter(b => b.id !== boardId));
          if (activeBoardId === boardId) {
            setActiveBoardId(null);
          }
          break;
        }

        case 'task_created': {
          const boardId = data.boardId as string || data.board_id as string;
          const task = data.task as Task;
          const columnId = data.columnId as string || data.column_id as string;
          console.log('[KanbanTab] Task created:', task.id, 'in column', columnId);
          setBoards(prev => prev.map(b => {
            if (b.id !== boardId) return b;
            const newTasks = { ...b.tasks, [task.id]: task };
            const newColumns = b.columns.map(col => {
              if (col.id !== columnId) return col;
              if (col.taskIds.includes(task.id)) return col;
              return { ...col, taskIds: [...col.taskIds, task.id] };
            });
            return { ...b, tasks: newTasks, columns: newColumns };
          }));
          // Auto-expand the column where task was added
          setExpandedColumns(prev => new Set([...prev, columnId]));
          break;
        }

        case 'task_updated': {
          const boardId = data.boardId as string || data.board_id as string;
          const task = data.task as Task;
          console.log('[KanbanTab] Task updated:', task.id);
          setBoards(prev => prev.map(b => {
            if (b.id !== boardId) return b;
            return { ...b, tasks: { ...b.tasks, [task.id]: task } };
          }));
          if (editingTask?.id === task.id) {
            setEditingTask(null);
          }
          break;
        }

        case 'task_deleted': {
          const boardId = data.boardId as string || data.board_id as string;
          const taskId = data.taskId as string || data.task_id as string;
          console.log('[KanbanTab] Task deleted:', taskId);
          setBoards(prev => prev.map(b => {
            if (b.id !== boardId) return b;
            const newTasks = { ...b.tasks };
            delete newTasks[taskId];
            const newColumns = b.columns.map(col => ({
              ...col,
              taskIds: col.taskIds.filter(id => id !== taskId),
            }));
            return { ...b, tasks: newTasks, columns: newColumns };
          }));
          break;
        }

        case 'task_moved': {
          const boardId = data.boardId as string || data.board_id as string;
          const taskId = data.taskId as string || data.task_id as string;
          const fromColumnId = data.fromColumnId as string || data.from_column_id as string;
          const toColumnId = data.toColumnId as string || data.to_column_id as string;
          const newPosition = data.newPosition as number || data.new_position as number || 0;
          console.log('[KanbanTab] Task moved:', taskId, fromColumnId, '->', toColumnId);
          setBoards(prev => prev.map(b => {
            if (b.id !== boardId) return b;
            const newColumns = b.columns.map(col => {
              if (col.id === fromColumnId) {
                return { ...col, taskIds: col.taskIds.filter(id => id !== taskId) };
              }
              if (col.id === toColumnId) {
                const newTaskIds = col.taskIds.filter(id => id !== taskId);
                newTaskIds.splice(newPosition, 0, taskId);
                return { ...col, taskIds: newTaskIds };
              }
              return col;
            });
            return { ...b, columns: newColumns };
          }));
          // Auto-expand the target column
          setExpandedColumns(prev => new Set([...prev, toColumnId]));
          break;
        }

        case 'board_state_sync':
        case 'kanban_state_sync': {
          const boardsList = data.boards as Board[] | undefined;
          console.log('[KanbanTab] State sync:', boardsList?.length, 'boards');
          if (boardsList) {
            setBoards(boardsList);
            if (boardsList.length > 0 && !activeBoardId) {
              setActiveBoardId(boardsList[0].id);
            }
          }
          break;
        }

        case 'all_boards_list': {
          const boardSummaries = data.boards as Array<{
            id: string;
            name: string;
            taskCount: number;
            sessionCount: number;
            createdAt: string;
          }>;
          console.log('[KanbanTab] All boards list:', boardSummaries?.length);
          if (boardSummaries) {
            // Filter out boards already linked to this session
            const linkedIds = new Set(boards.map(b => b.id));
            const available = boardSummaries.filter(b => !linkedIds.has(b.id));
            // Convert to Board-like objects for display (minimal info)
            setAllBoards(available.map(b => ({
              id: b.id,
              name: b.name,
              columns: [],
              tasks: {},
              defaultColumnId: '',
              createdAt: b.createdAt,
              // Extra fields for picker
              _taskCount: b.taskCount,
              _sessionCount: b.sessionCount,
            } as Board & { _taskCount?: number; _sessionCount?: number })));
          }
          break;
        }

        case 'board_associated': {
          const board = data.board as Board;
          console.log('[KanbanTab] Board associated:', board.id);
          setBoards(prev => {
            if (prev.some(b => b.id === board.id)) {
              return prev;
            }
            return [...prev, board];
          });
          // Remove from allBoards since it's now linked
          setAllBoards(prev => prev.filter(b => b.id !== board.id));
          setActiveBoardId(board.id);
          setShowBoardList(false);
          break;
        }

        case 'board_unlinked': {
          const boardId = data.board_id as string;
          console.log('[KanbanTab] Board unlinked:', boardId);
          setBoards(prev => prev.filter(b => b.id !== boardId));
          // If viewing that board, go back to list
          if (activeBoardId === boardId) {
            setShowBoardList(true);
            setActiveBoardId(null);
          }
          // Refresh all boards list
          if (callDomainMethod) {
            callDomainMethod('kanbanListAllBoards', {});
          }
          break;
        }
      }
    });

    return unsubscribe;
  }, [subscribeToDomainEvents, sessionId, activeBoardId, editingTask?.id]);

  // Request current state on mount
  useEffect(() => {
    if (!requestDomainState || !sessionId) return;

    console.log('[KanbanTab] Requesting kanban state for session:', sessionId);
    requestDomainState('kanban').then((hasState) => {
      console.log('[KanbanTab] State request result:', hasState);
    }).catch((err) => {
      console.warn('[KanbanTab] Failed to request domain state:', err);
    });
  }, [requestDomainState, sessionId]);

  // Auto-load all boards once when no boards are linked (for the inline picker)
  const hasLoadedAllBoards = React.useRef(false);
  useEffect(() => {
    if (boards.length === 0 && callDomainMethod && !hasLoadedAllBoards.current) {
      hasLoadedAllBoards.current = true;
      setIsLoadingAllBoards(true);
      callDomainMethod('kanbanListAllBoards', {}).finally(() => {
        setIsLoadingAllBoards(false);
      });
    }
    // Reset if boards become linked then unlinked
    if (boards.length > 0) {
      hasLoadedAllBoards.current = false;
    }
  }, [boards.length, callDomainMethod]);

  // Load all boards when entering board list view
  useEffect(() => {
    if (showBoardList && callDomainMethod) {
      callDomainMethod('kanbanListAllBoards', {});
    }
  }, [showBoardList, callDomainMethod]);

  // Toggle column expansion
  const toggleColumn = useCallback((columnId: string) => {
    setExpandedColumns(prev => {
      const next = new Set(prev);
      if (next.has(columnId)) {
        next.delete(columnId);
      } else {
        next.add(columnId);
      }
      return next;
    });
  }, []);

  // Handle creating a new task
  const handleCreateTask = useCallback(async (columnId: string) => {
    if (!callDomainMethod || !newTaskTitle.trim() || !activeBoard) return;

    setIsSubmitting(true);
    try {
      await callDomainMethod('kanbanCreateTask', {
        title: newTaskTitle.trim(),
        board_id: activeBoard.id,
        column_id: columnId,
      });
      setNewTaskTitle('');
      setIsCreatingTask(false);
      setNewTaskColumn(null);
    } catch (e) {
      console.error('[KanbanTab] Failed to create task:', e);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod, newTaskTitle, activeBoard]);

  // Handle updating a task
  const handleUpdateTask = useCallback(async () => {
    if (!callDomainMethod || !editingTask) return;

    setIsSubmitting(true);
    try {
      await callDomainMethod('kanbanUpdateTask', {
        task_id: editingTask.id,
        title: editForm.title.trim() || undefined,
        description: editForm.description.trim() || undefined,
        resolution: editForm.resolution.trim() || undefined,
      });
      setEditingTask(null);
    } catch (e) {
      console.error('[KanbanTab] Failed to update task:', e);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod, editingTask, editForm]);

  // Handle deleting a task
  const handleDeleteTask = useCallback(async (taskId: string, taskTitle: string) => {
    if (!callDomainMethod) return;

    const shouldDelete = confirm
      ? await confirm({
          title: 'Delete Task',
          message: `Are you sure you want to delete "${taskTitle}"?`,
          confirmText: 'Delete',
          variant: 'danger',
        })
      : window.confirm(`Delete task "${taskTitle}"?`);

    if (!shouldDelete) return;

    try {
      await callDomainMethod('kanbanDeleteTask', { task_id: taskId });
    } catch (e) {
      console.error('[KanbanTab] Failed to delete task:', e);
    }
  }, [callDomainMethod, confirm]);

  // Handle unlinking a board from the session
  const handleUnlinkBoard = useCallback(async (boardId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    if (!callDomainMethod) return;

    setIsSubmitting(true);
    try {
      await callDomainMethod('kanbanUnlinkBoard', { board_id: boardId });
    } catch (err) {
      console.error('[KanbanTab] Failed to unlink board:', err);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod]);

  // View a board without linking (just for viewing)
  const handleViewBoard = useCallback((board: Board) => {
    // Add to boards temporarily for viewing
    setBoards(prev => {
      if (prev.some(b => b.id === board.id)) return prev;
      return [...prev, { ...board, _viewOnly: true } as Board];
    });
    setActiveBoardId(board.id);
    setShowBoardList(false);
  }, []);

  // Format date for display
  const formatDate = useCallback((dateStr: string) => {
    try {
      const date = new Date(dateStr);
      const now = new Date();
      const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24));
      if (diffDays === 0) return 'today';
      if (diffDays === 1) return 'yesterday';
      if (diffDays < 7) return `${diffDays}d ago`;
      return date.toLocaleDateString();
    } catch {
      return '';
    }
  }, []);

  // Handle moving a task between columns
  const handleMoveTask = useCallback(async (taskId: string, toColumnId: string, position?: number) => {
    if (!callDomainMethod || !activeBoard) return;

    const task = activeBoard.tasks[taskId];
    if (!task) return;

    const toColumn = activeBoard.columns.find(c => c.id === toColumnId);
    if (!toColumn) return;

    try {
      await callDomainMethod('kanbanMoveTask', {
        task: taskId,
        to_column: toColumn.name,
        position: position,
      });
    } catch (e) {
      console.error('[KanbanTab] Failed to move task:', e);
    }
  }, [callDomainMethod, activeBoard]);

  // Handle creating a new board
  const handleCreateBoard = useCallback(async () => {
    if (!callDomainMethod || !newBoardName.trim()) return;

    setIsSubmitting(true);
    try {
      await callDomainMethod('kanbanCreateBoard', {
        name: newBoardName.trim(),
      });
      setNewBoardName('');
      setShowBoardForm(false);
    } catch (e) {
      console.error('[KanbanTab] Failed to create board:', e);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod, newBoardName]);

  // Load all boards for the picker
  const loadAllBoards = useCallback(async () => {
    if (!callDomainMethod) return;

    setIsLoadingAllBoards(true);
    try {
      const result = await callDomainMethod('kanbanListAllBoards', {});
      // The response is a text result, but we need the actual board data
      // We'll need to parse it or add a ws_expose method that returns JSON
      // For now, let's request domain state which gives us full board objects
      // Actually, let's make a separate call - we need the raw board data
      // The listAllBoards method returns text, but we can parse the board data
      // from it or add a new method. For now, let's just show the picker modal
      // and let the user select by name
      console.log('[KanbanTab] All boards result:', result);
    } catch (e) {
      console.error('[KanbanTab] Failed to load all boards:', e);
    } finally {
      setIsLoadingAllBoards(false);
    }
  }, [callDomainMethod]);

  // Link an existing board to this session
  const handleLinkBoard = useCallback(async (boardId: string) => {
    if (!callDomainMethod) return;

    setIsSubmitting(true);
    try {
      await callDomainMethod('kanbanLinkBoard', {
        board_id: boardId,
      });
      setShowBoardPicker(false);
      // Request updated state
      if (requestDomainState) {
        requestDomainState('kanban');
      }
    } catch (e) {
      console.error('[KanbanTab] Failed to link board:', e);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod, requestDomainState]);

  // Drag handlers
  const handleDragStart = useCallback((e: React.DragEvent, taskId: string, columnId: string, index: number) => {
    setDragState({ taskId, sourceColumnId: columnId, sourceIndex: index });
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', taskId);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent, columnId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDropTargetColumn(columnId);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = e.clientX;
    const y = e.clientY;
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
      setDropTargetColumn(null);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent, columnId: string) => {
    e.preventDefault();
    setDropTargetColumn(null);

    if (!dragState) return;

    if (dragState.sourceColumnId === columnId) {
      setDragState(null);
      return;
    }

    handleMoveTask(dragState.taskId, columnId);
    setDragState(null);
  }, [dragState, handleMoveTask]);

  const handleDragEnd = useCallback(() => {
    setDragState(null);
    setDropTargetColumn(null);
  }, []);

  // Open edit form for a task
  const openEditForm = useCallback((task: Task) => {
    setEditingTask(task);
    setEditForm({
      title: task.title,
      description: task.description,
      resolution: task.resolution,
    });
  }, []);

  // Render empty state
  if (boards.length === 0) {
    return (
      <div className="kanban-tab kanban-tab--no-boards">
        {/* New board form - inline */}
        <div className="kanban-new-board-section">
          <div className="kanban-new-board-form">
            <input
              type="text"
              value={newBoardName}
              onChange={e => setNewBoardName(e.target.value)}
              placeholder="New board name..."
              onKeyDown={e => {
                if (e.key === 'Enter' && newBoardName.trim()) {
                  handleCreateBoard();
                }
              }}
            />
            <button
              className="kanban-btn kanban-btn--primary"
              onClick={handleCreateBoard}
              disabled={!newBoardName.trim() || isSubmitting}
            >
              {isSubmitting ? '...' : '+'}
            </button>
          </div>
        </div>

        {/* Existing boards list - inline */}
        <div className="kanban-boards-section">
          {isLoadingAllBoards ? (
            <div className="kanban-boards-loading">Loading boards...</div>
          ) : allBoards.length === 0 ? (
            <div className="kanban-boards-empty">No existing boards</div>
          ) : (
            <>
              <div className="kanban-boards-header">Existing boards</div>
              <div className="kanban-boards-list">
                {allBoards.map(board => {
                  const b = board as Board & { _taskCount?: number; _sessionCount?: number };
                  return (
                    <button
                      key={board.id}
                      className="kanban-board-item"
                      onClick={() => handleLinkBoard(board.id)}
                      disabled={isSubmitting}
                    >
                      <div className="kanban-board-item-name">{board.name}</div>
                      <div className="kanban-board-item-meta">
                        {b._taskCount ?? 0} tasks
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // Board list view
  if (showBoardList) {
    return (
      <div className="kanban-tab kanban-tab--no-boards">
        {/* Header with back indication */}
        <div className="kanban-list-header">
          <span className="kanban-list-title">Boards</span>
        </div>

        {/* New board form - inline */}
        <div className="kanban-new-board-section">
          <div className="kanban-new-board-form">
            <input
              type="text"
              value={newBoardName}
              onChange={e => setNewBoardName(e.target.value)}
              placeholder="New board name..."
              onKeyDown={e => {
                if (e.key === 'Enter' && newBoardName.trim()) {
                  handleCreateBoard();
                }
              }}
            />
            <button
              className="kanban-btn kanban-btn--primary"
              onClick={handleCreateBoard}
              disabled={!newBoardName.trim() || isSubmitting}
            >
              {isSubmitting ? '...' : '+'}
            </button>
          </div>
        </div>

        {/* Linked boards */}
        {boards.filter(b => !(b as any)._viewOnly).length > 0 && (
          <div className="kanban-boards-section">
            <div className="kanban-boards-header">Linked</div>
            <div className="kanban-boards-list">
              {boards.filter(b => !(b as any)._viewOnly).map(board => (
                <div key={board.id} className="kanban-board-item kanban-board-item--linked">
                  <div
                    className="kanban-board-item-main"
                    onClick={() => {
                      setActiveBoardId(board.id);
                      setShowBoardList(false);
                    }}
                  >
                    <div className="kanban-board-item-name">{board.name}</div>
                    <div className="kanban-board-item-meta">
                      <span>{Object.keys(board.tasks).length} tasks</span>
                      <span>{formatDate(board.createdAt)}</span>
                    </div>
                  </div>
                  <button
                    className="kanban-board-item-action kanban-board-item-action--unlink"
                    onClick={(e) => handleUnlinkBoard(board.id, e)}
                    disabled={isSubmitting}
                    title="Unlink from session"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Available boards to link */}
        <div className="kanban-boards-section">
          {isLoadingAllBoards ? (
            <div className="kanban-boards-loading">Loading boards...</div>
          ) : allBoards.length === 0 ? (
            boards.length === 0 && <div className="kanban-boards-empty">No boards yet</div>
          ) : (
            <>
              <div className="kanban-boards-header">Available</div>
              <div className="kanban-boards-list">
                {allBoards.map(board => {
                  const b = board as Board & { _taskCount?: number; _sessionCount?: number };
                  return (
                    <div key={board.id} className="kanban-board-item">
                      <div
                        className="kanban-board-item-main"
                        onClick={() => handleViewBoard(board)}
                        title="View board (without linking)"
                      >
                        <div className="kanban-board-item-name">{board.name}</div>
                        <div className="kanban-board-item-meta">
                          <span>{b._taskCount ?? 0} tasks</span>
                          <span>{formatDate(board.createdAt)}</span>
                        </div>
                      </div>
                      <button
                        className="kanban-board-item-action kanban-board-item-action--link"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleLinkBoard(board.id);
                        }}
                        disabled={isSubmitting}
                        title="Link to session"
                      >
                        +
                      </button>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    );
  }

  // Check if current board is view-only (not linked)
  const isViewOnly = activeBoard && (activeBoard as any)._viewOnly;

  return (
    <div className="kanban-tab">
      {/* Board Header */}
      <div className="kanban-header">
        <div className="kanban-board-selector">
          <button
            className="kanban-back-btn"
            onClick={() => setShowBoardList(true)}
            title="Back to board list"
          >
            ←
          </button>
          <h2 className="kanban-board-title">{activeBoard?.name || 'Board'}</h2>
          {isViewOnly && (
            <span className="kanban-board-badge kanban-board-badge--view">viewing</span>
          )}
        </div>
        <div className="kanban-header-actions">
          {isViewOnly && callDomainMethod && (
            <button
              className="kanban-btn kanban-btn--small kanban-btn--primary"
              onClick={() => activeBoard && handleLinkBoard(activeBoard.id)}
              disabled={isSubmitting}
              title="Link to session"
            >
              Link
            </button>
          )}
          {!isViewOnly && activeBoard && callDomainMethod && (
            <button
              className="kanban-btn kanban-btn--small"
              onClick={() => activeBoard && handleUnlinkBoard(activeBoard.id)}
              disabled={isSubmitting}
              title="Unlink from session"
            >
              Unlink
            </button>
          )}
          {requestDomainState && (
            <button
              className="kanban-btn kanban-btn--icon"
              onClick={() => requestDomainState('kanban')}
              title="Refresh"
            >
              ↻
            </button>
          )}
        </div>
      </div>

      {/* Vertical Accordion Layout */}
      {activeBoard && (
        <div className="kanban-accordion-container">
          {activeBoard.columns
            .slice()
            .sort((a, b) => a.position - b.position)
            .map(column => {
              const isExpanded = expandedColumns.has(column.id);
              const isDropTarget = dropTargetColumn === column.id;
              const taskCount = column.taskIds.length;

              return (
                <div
                  key={column.id}
                  className={`kanban-accordion ${isExpanded ? 'kanban-accordion--expanded' : ''} ${isDropTarget ? 'kanban-accordion--drop-target' : ''}`}
                  onDragOver={e => handleDragOver(e, column.id)}
                  onDragLeave={handleDragLeave}
                  onDrop={e => handleDrop(e, column.id)}
                >
                  {/* Accordion Header */}
                  <button
                    className="kanban-accordion-header"
                    onClick={() => toggleColumn(column.id)}
                  >
                    <span className={`kanban-accordion-icon ${isExpanded ? 'kanban-accordion-icon--expanded' : ''}`}>
                      ▶
                    </span>
                    <span className="kanban-accordion-title">{column.name}</span>
                    <span className="kanban-accordion-count">{taskCount}</span>
                    {callDomainMethod && (
                      <button
                        className="kanban-accordion-add-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          setIsCreatingTask(true);
                          setNewTaskColumn(column.id);
                          if (!isExpanded) {
                            setExpandedColumns(prev => new Set([...prev, column.id]));
                          }
                        }}
                        title="Add task"
                      >
                        +
                      </button>
                    )}
                  </button>

                  {/* Accordion Content */}
                  {isExpanded && (
                    <div className="kanban-accordion-content">
                      {/* New task input */}
                      {isCreatingTask && newTaskColumn === column.id && (
                        <div className="kanban-new-task-form">
                          <input
                            type="text"
                            value={newTaskTitle}
                            onChange={e => setNewTaskTitle(e.target.value)}
                            placeholder="Enter task title..."
                            autoFocus
                            onKeyDown={e => {
                              if (e.key === 'Enter' && newTaskTitle.trim()) {
                                handleCreateTask(column.id);
                              } else if (e.key === 'Escape') {
                                setIsCreatingTask(false);
                                setNewTaskColumn(null);
                                setNewTaskTitle('');
                              }
                            }}
                            onBlur={() => {
                              if (!newTaskTitle.trim()) {
                                setIsCreatingTask(false);
                                setNewTaskColumn(null);
                              }
                            }}
                          />
                          <div className="kanban-new-task-actions">
                            <button
                              className="kanban-btn kanban-btn--small kanban-btn--primary"
                              onClick={() => handleCreateTask(column.id)}
                              disabled={!newTaskTitle.trim() || isSubmitting}
                            >
                              Add
                            </button>
                            <button
                              className="kanban-btn kanban-btn--small"
                              onClick={() => {
                                setIsCreatingTask(false);
                                setNewTaskColumn(null);
                                setNewTaskTitle('');
                              }}
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Tasks */}
                      {taskCount === 0 && !(isCreatingTask && newTaskColumn === column.id) ? (
                        <div className="kanban-accordion-empty">No tasks</div>
                      ) : (
                        column.taskIds.map((taskId, index) => {
                          const task = activeBoard.tasks[taskId];
                          if (!task) return null;

                          const isDragging = dragState?.taskId === taskId;

                          return (
                            <div
                              key={taskId}
                              className={`kanban-task ${isDragging ? 'kanban-task--dragging' : ''}`}
                              draggable
                              onDragStart={e => handleDragStart(e, taskId, column.id, index)}
                              onDragEnd={handleDragEnd}
                              onClick={() => openEditForm(task)}
                            >
                              <div className="kanban-task-title">{task.title}</div>
                              {task.description && (
                                <div className="kanban-task-description">
                                  {task.description.length > 60
                                    ? task.description.slice(0, 60) + '...'
                                    : task.description}
                                </div>
                              )}
                              {task.resolution && (
                                <div className="kanban-task-resolution">
                                  <span className="kanban-task-resolution-badge">✓</span>
                                  {task.resolution.length > 40
                                    ? task.resolution.slice(0, 40) + '...'
                                    : task.resolution}
                                </div>
                              )}
                              {/* Quick move buttons - horizontal row */}
                              <div className="kanban-task-quick-actions">
                                {activeBoard.columns
                                  .filter(c => c.id !== column.id)
                                  .map(targetCol => (
                                    <button
                                      key={targetCol.id}
                                      className="kanban-task-move-btn"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        handleMoveTask(taskId, targetCol.id);
                                      }}
                                      title={`Move to ${targetCol.name}`}
                                    >
                                      {targetCol.name}
                                    </button>
                                  ))}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      )}

      {/* Edit Task Modal */}
      {editingTask && (
        <div className="kanban-modal-overlay" onClick={() => setEditingTask(null)}>
          <div className="kanban-modal kanban-modal--edit" onClick={e => e.stopPropagation()}>
            <div className="kanban-modal-header">
              <h3>Edit Task</h3>
              <button className="kanban-modal-close" onClick={() => setEditingTask(null)}>
                ×
              </button>
            </div>
            <div className="kanban-modal-body">
              <div className="kanban-form-group">
                <label>Title</label>
                <input
                  type="text"
                  value={editForm.title}
                  onChange={e => setEditForm(f => ({ ...f, title: e.target.value }))}
                  placeholder="Task title"
                />
              </div>
              <div className="kanban-form-group">
                <label>Description</label>
                <textarea
                  value={editForm.description}
                  onChange={e => setEditForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Optional description"
                  rows={3}
                />
              </div>
              <div className="kanban-form-group">
                <label>Resolution</label>
                <textarea
                  value={editForm.resolution}
                  onChange={e => setEditForm(f => ({ ...f, resolution: e.target.value }))}
                  placeholder="What was done to complete this task?"
                  rows={3}
                />
                <span className="kanban-form-hint">
                  Document what was accomplished when the task is done
                </span>
              </div>
              <div className="kanban-task-meta">
                <span>ID: {editingTask.id.slice(0, 8)}...</span>
                <span>Created: {new Date(editingTask.createdAt).toLocaleDateString()}</span>
              </div>
            </div>
            <div className="kanban-modal-footer">
              <button
                className="kanban-btn kanban-btn--danger"
                onClick={() => {
                  handleDeleteTask(editingTask.id, editingTask.title);
                  setEditingTask(null);
                }}
              >
                Delete
              </button>
              <div className="kanban-modal-footer-right">
                <button
                  className="kanban-btn kanban-btn--secondary"
                  onClick={() => setEditingTask(null)}
                >
                  Cancel
                </button>
                <button
                  className="kanban-btn kanban-btn--primary"
                  onClick={handleUpdateTask}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? 'Saving...' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export default KanbanTab;
