/**
 * Type definitions for the Kanban plugin
 */

export interface Task {
  id: string;
  title: string;
  description: string;
  resolution: string;
  priority: 'low' | 'medium' | 'high' | 'urgent';
  createdAt: string;
  updatedAt: string;
}

export interface Column {
  id: string;
  name: string;
  position: number;
  taskIds: string[];
}

export interface Board {
  id: string;
  name: string;
  columns: Column[];
  tasks: Record<string, Task>;
  defaultColumnId: string;
  createdAt: string;
}

export interface SessionBoardAssociation {
  id: string;
  sessionId: string;
  boardId: string;
  role: string;
  createdAt: string;
  createdBy: string;
  inheritedFrom: string | null;
}

// Plugin context provided by the host app
export interface PluginContext {
  /** Send a message to the LLM */
  sendMessage?: (message: string) => void;
  /** Current session ID */
  sessionId?: string;
  /** Subscribe to domain events, returns unsubscribe function */
  subscribeToDomainEvents?: (
    domainId: string,
    callback: (event: DomainEventData) => void
  ) => () => void;
  /** Request current domain state */
  requestDomainState?: (domainId: string) => Promise<boolean>;
  /** Whether the LLM is currently responding (streaming) */
  isLLMResponding?: boolean;
  /** Show confirmation dialog */
  confirm?: (options: ConfirmOptions) => Promise<boolean>;
  /** Call a @ws_expose method on a domain plugin */
  callDomainMethod?: (
    methodName: string,
    params?: Record<string, unknown> | null
  ) => Promise<Record<string, unknown>>;
}

export interface DomainEventData {
  sessionId: string;
  domainId: string;
  eventType: string;
  data: Record<string, unknown>;
}

export interface ConfirmOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'default' | 'danger' | 'warning' | 'success';
}

// Drag state for kanban interactions
export interface DragState {
  taskId: string;
  sourceColumnId: string;
  sourceIndex: number;
}
