/**
 * SessionKanbanTab - Session-specific kanban board management
 *
 * Shows boards associated with the current session:
 * - Auto-loads boards for the session via getBoardsForSession
 * - Empty state with "Create Board" and "Link Existing" options
 * - Auto-selects single board; shows selector for multiple
 * - Reuses BoardView from KanbanTab for board display
 * - Real-time updates via boardAssociated/boardDisassociated events
 *
 * Boards are inherited on fork, so child sessions start with parent's boards.
 */

import React, { useState, useEffect, useCallback, memo } from 'react';
import type {
  BoardInfo,
  BoardStateInfo,
  BoardAssociationInfo,
  KanbanWebSocketServiceClient,
} from '../../../../generated/balloons-client';
import { BoardView } from '../KanbanTab';
import '../KanbanTab/KanbanTab.css';
import './SessionKanbanTab.css';

// =============================================================================
// Types
// =============================================================================

export interface SessionKanbanTabProps {
  /** Current session ID */
  sessionId: string | null;
  /** Kanban service client */
  kanbanClient?: KanbanWebSocketServiceClient;
  /** Client ID for subscriptions */
  clientId?: string;
  /** Whether connected to server */
  isConnected: boolean;
}

interface SessionBoard {
  association: BoardAssociationInfo;
  board: BoardInfo;
}

// =============================================================================
// Empty State Component
// =============================================================================

function EmptyState({
  onCreateBoard,
  onLinkBoard,
  isCreating,
  allBoards,
}: {
  onCreateBoard: () => void;
  onLinkBoard: (boardId: string) => void;
  isCreating: boolean;
  allBoards: BoardInfo[];
}) {
  const [showLinkModal, setShowLinkModal] = useState(false);

  return (
    <div className="session-kanban-empty">
      <div className="session-kanban-empty__icon">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <line x1="9" y1="3" x2="9" y2="21" />
          <line x1="15" y1="3" x2="15" y2="21" />
        </svg>
      </div>
      <h3>No boards for this session</h3>
      <p>Create a new board or link an existing one to track tasks.</p>
      <div className="session-kanban-empty__actions">
        <button
          className="kanban-btn kanban-btn--primary"
          onClick={onCreateBoard}
          disabled={isCreating}
        >
          {isCreating ? 'Creating...' : '+ Create Board'}
        </button>
        {allBoards.length > 0 && (
          <button
            className="kanban-btn"
            onClick={() => setShowLinkModal(true)}
          >
            Link Existing
          </button>
        )}
      </div>

      {/* Link Board Modal */}
      {showLinkModal && (
        <div className="kanban-modal-overlay" onClick={() => setShowLinkModal(false)}>
          <div className="kanban-modal" onClick={(e) => e.stopPropagation()}>
            <div className="kanban-modal__header">
              <h3>Link Existing Board</h3>
              <button className="kanban-modal__close" onClick={() => setShowLinkModal(false)}>
                ×
              </button>
            </div>
            <div className="kanban-modal__content">
              {allBoards.length === 0 ? (
                <p>No boards available to link.</p>
              ) : (
                <div className="session-kanban-link-list">
                  {allBoards.map((board) => (
                    <button
                      key={board.id}
                      className="session-kanban-link-item"
                      onClick={() => {
                        onLinkBoard(board.id);
                        setShowLinkModal(false);
                      }}
                    >
                      <span className="session-kanban-link-item__name">{board.name}</span>
                      <span className="session-kanban-link-item__date">
                        {new Date(board.createdAt).toLocaleDateString()}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Board Selector Component (when multiple boards)
// =============================================================================

function BoardSelector({
  boards,
  selectedBoardId,
  onSelectBoard,
  onCreateBoard,
  onUnlinkBoard,
  isCreating,
}: {
  boards: SessionBoard[];
  selectedBoardId: string | null;
  onSelectBoard: (boardId: string) => void;
  onCreateBoard: () => void;
  onUnlinkBoard: (boardId: string) => void;
  isCreating: boolean;
}) {
  return (
    <div className="session-kanban-selector">
      <div className="session-kanban-selector__header">
        <span>Session Boards</span>
        <button
          className="kanban-btn kanban-btn--small"
          onClick={onCreateBoard}
          disabled={isCreating}
          title="Create new board"
        >
          +
        </button>
      </div>
      <div className="session-kanban-selector__list">
        {boards.map(({ association, board }) => (
          <div
            key={board.id}
            className={`session-kanban-selector__item ${selectedBoardId === board.id ? 'selected' : ''}`}
            onClick={() => onSelectBoard(board.id)}
          >
            <span className="session-kanban-selector__item-name">{board.name}</span>
            {association.role && (
              <span className="session-kanban-selector__item-role">{association.role}</span>
            )}
            {association.inheritedFrom && (
              <span className="session-kanban-selector__item-inherited" title="Inherited from parent session">
                ↩
              </span>
            )}
            <button
              className="session-kanban-selector__item-unlink"
              onClick={(e) => {
                e.stopPropagation();
                if (confirm(`Unlink "${board.name}" from this session?`)) {
                  onUnlinkBoard(board.id);
                }
              }}
              title="Unlink board from session"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// Main Component
// =============================================================================

export const SessionKanbanTab = memo(function SessionKanbanTab({
  sessionId,
  kanbanClient,
  clientId,
  isConnected,
}: SessionKanbanTabProps) {
  // Session boards state
  const [sessionBoards, setSessionBoards] = useState<SessionBoard[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // All boards (for linking)
  const [allBoards, setAllBoards] = useState<BoardInfo[]>([]);

  // Selected board state
  const [selectedBoardId, setSelectedBoardId] = useState<string | null>(null);
  const [boardState, setBoardState] = useState<BoardStateInfo | null>(null);
  const [isLoadingBoard, setIsLoadingBoard] = useState(false);

  // Load session boards
  useEffect(() => {
    if (!kanbanClient || !isConnected || !sessionId) {
      setSessionBoards([]);
      setIsLoading(false);
      return;
    }

    const loadBoards = async () => {
      try {
        setIsLoading(true);
        setError(null);

        // Load boards for this session
        const result = await kanbanClient.getBoardsForSession(sessionId);
        const boards: SessionBoard[] = result.associations.map((assoc) => ({
          association: assoc,
          board: result.boards.find((b) => b.id === assoc.boardId)!,
        })).filter((sb) => sb.board); // Filter out any missing boards

        setSessionBoards(boards);

        // Auto-select if single board
        if (boards.length === 1 && boards[0]) {
          setSelectedBoardId(boards[0].board.id);
        } else if (boards.length === 0) {
          setSelectedBoardId(null);
        }

        // Also load all boards for linking
        const allBoardList = await kanbanClient.listBoards();
        setAllBoards(allBoardList);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load boards');
      } finally {
        setIsLoading(false);
      }
    };

    loadBoards();
  }, [kanbanClient, isConnected, sessionId]);

  // Subscribe to board association events
  useEffect(() => {
    if (!kanbanClient || !sessionId) return;

    const unsubAssociated = kanbanClient.boardAssociated((event) => {
      if (event.association.sessionId !== sessionId) return;

      setSessionBoards((prev) => {
        // Check if already exists
        if (prev.some((sb) => sb.board.id === event.board.id)) return prev;
        return [...prev, { association: event.association, board: event.board }];
      });

      // Auto-select if it's the only board
      setSessionBoards((prev) => {
        if (prev.length === 1 && prev[0]) {
          setSelectedBoardId(prev[0].board.id);
        }
        return prev;
      });
    });

    const unsubDisassociated = kanbanClient.boardDisassociated((event) => {
      if (event.sessionId !== sessionId) return;

      setSessionBoards((prev) => prev.filter((sb) => sb.board.id !== event.boardId));

      // Clear selection if the removed board was selected
      if (selectedBoardId === event.boardId) {
        setSelectedBoardId(null);
        setBoardState(null);
      }
    });

    // Also subscribe to board creation (for allBoards list)
    const unsubCreated = kanbanClient.boardCreated((event) => {
      setAllBoards((prev) => [...prev, event.board.board]);
    });

    const unsubDeleted = kanbanClient.boardDeleted((event) => {
      setAllBoards((prev) => prev.filter((b) => b.id !== event.boardId));
      setSessionBoards((prev) => prev.filter((sb) => sb.board.id !== event.boardId));
      if (selectedBoardId === event.boardId) {
        setSelectedBoardId(null);
        setBoardState(null);
      }
    });

    return () => {
      unsubAssociated();
      unsubDisassociated();
      unsubCreated();
      unsubDeleted();
    };
  }, [kanbanClient, sessionId, selectedBoardId]);

  // Subscribe to selected board for state updates
  useEffect(() => {
    if (!kanbanClient || !clientId || !selectedBoardId) {
      setBoardState(null);
      return;
    }

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
        const newTasks = [...prev.tasks, event.task];
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
        const newTasks = prev.tasks.filter((t) => t.id !== event.taskId);
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
  const handleCreateBoard = useCallback(async () => {
    if (!kanbanClient || !sessionId) return;

    try {
      setIsCreating(true);
      const board = await kanbanClient.createBoardForSession(sessionId, 'Session Board');
      if (board) {
        // Board will be added via event, auto-select it
        setSelectedBoardId(board.board.id);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create board');
    } finally {
      setIsCreating(false);
    }
  }, [kanbanClient, sessionId]);

  const handleLinkBoard = useCallback(async (boardId: string) => {
    if (!kanbanClient || !sessionId) return;

    try {
      await kanbanClient.associateBoardWithSession(boardId, sessionId);
      // Board will be added via event
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to link board');
    }
  }, [kanbanClient, sessionId]);

  const handleUnlinkBoard = useCallback(async (boardId: string) => {
    if (!kanbanClient || !sessionId) return;

    try {
      await kanbanClient.dissociateBoardFromSession(boardId, sessionId);
      // Board will be removed via event
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to unlink board');
    }
  }, [kanbanClient, sessionId]);

  const handleBackToList = useCallback(() => {
    setSelectedBoardId(null);
    setBoardState(null);
  }, []);

  // Not connected state
  if (!isConnected) {
    return (
      <div className="session-kanban-tab">
        <div className="session-kanban-tab__disconnected">
          <span className="kanban-connection-status">○</span>
          <span>Connect to server to manage kanban boards</span>
        </div>
      </div>
    );
  }

  // No session selected
  if (!sessionId) {
    return (
      <div className="session-kanban-tab">
        <div className="session-kanban-tab__no-session">
          <span>Select a session to view its boards</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="session-kanban-tab">
        <div className="session-kanban-tab__error">
          <span className="session-kanban-tab__error-icon">!</span>
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

  // Loading state
  if (isLoading) {
    return (
      <div className="session-kanban-tab session-kanban-tab--loading">
        Loading session boards...
      </div>
    );
  }

  // Empty state - no boards for this session
  if (sessionBoards.length === 0) {
    // Filter out boards already associated with this session
    const availableBoards = allBoards.filter(
      (b) => !sessionBoards.some((sb) => sb.board.id === b.id)
    );

    return (
      <div className="session-kanban-tab">
        <EmptyState
          onCreateBoard={handleCreateBoard}
          onLinkBoard={handleLinkBoard}
          isCreating={isCreating}
          allBoards={availableBoards}
        />
      </div>
    );
  }

  // Loading selected board
  if (selectedBoardId && isLoadingBoard) {
    return (
      <div className="session-kanban-tab session-kanban-tab--loading">
        Loading board...
      </div>
    );
  }

  // Board view (single board or board selected from list)
  if (selectedBoardId && boardState && kanbanClient && clientId) {
    return (
      <div className="session-kanban-tab">
        {/* Show selector if multiple boards */}
        {sessionBoards.length > 1 && (
          <BoardSelector
            boards={sessionBoards}
            selectedBoardId={selectedBoardId}
            onSelectBoard={setSelectedBoardId}
            onCreateBoard={handleCreateBoard}
            onUnlinkBoard={handleUnlinkBoard}
            isCreating={isCreating}
          />
        )}
        <BoardView
          boardState={boardState}
          kanbanClient={kanbanClient}
          clientId={clientId}
          onBack={sessionBoards.length > 1 ? undefined : handleBackToList}
        />
      </div>
    );
  }

  // Multiple boards, none selected - show selector
  return (
    <div className="session-kanban-tab">
      <BoardSelector
        boards={sessionBoards}
        selectedBoardId={selectedBoardId}
        onSelectBoard={setSelectedBoardId}
        onCreateBoard={handleCreateBoard}
        onUnlinkBoard={handleUnlinkBoard}
        isCreating={isCreating}
      />
      <div className="session-kanban-tab__select-prompt">
        Select a board to view its tasks
      </div>
    </div>
  );
});

export default SessionKanbanTab;
