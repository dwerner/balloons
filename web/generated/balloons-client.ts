/**
 * Balloons Unified WebSocket Client
 *
 * Provides a single entry point for connecting to the Balloons backend
 * and accessing all service clients.
 *
 * Usage:
 *   const client = new BalloonsClient('ws://localhost:8765');
 *   await client.connect();
 *
 *   // Access service clients
 *   const sessions = await client.sessions.listSessions();
 *   const turns = await client.tree.getTurns(sessionId);
 *
 *   // Subscribe to events
 *   client.tree.onTurnUpdated((data) => console.log('Turn:', data));
 *
 *   // Disconnect
 *   client.disconnect();
 */

import {
  TreeStateServiceClient,
  QueueStateServiceClient,
  SessionManagerServiceClient,
  GoalTreeStateServiceClient,
  TaskStateServiceClient,
} from './client';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface BalloonsClientOptions {
  /** Reconnect automatically on disconnect (default: true) */
  autoReconnect?: boolean;

  /** Delay between reconnection attempts in ms (default: 1000) */
  reconnectDelay?: number;

  /** Maximum reconnection attempts (default: 10) */
  maxReconnectAttempts?: number;

  /** JWT token for authentication */
  token?: string;
}

export class BalloonsClient {
  private ws: WebSocket | null = null;
  private url: string;
  private options: Required<BalloonsClientOptions>;
  private reconnectAttempts = 0;
  private reconnectTimer: number | null = null;

  // Connection state
  private _state: ConnectionState = 'disconnected';
  private stateListeners: Set<(state: ConnectionState) => void> = new Set();

  // Service clients (lazily initialized)
  private _tree: TreeStateServiceClient | null = null;
  private _queue: QueueStateServiceClient | null = null;
  private _sessions: SessionManagerServiceClient | null = null;
  private _goals: GoalTreeStateServiceClient | null = null;
  private _tasks: TaskStateServiceClient | null = null;

  constructor(url: string, options: BalloonsClientOptions = {}) {
    this.url = url;
    this.options = {
      autoReconnect: options.autoReconnect ?? true,
      reconnectDelay: options.reconnectDelay ?? 1000,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 10,
      token: options.token ?? '',
    };
  }

  /** Get current connection state */
  get state(): ConnectionState {
    return this._state;
  }

  /** Check if connected */
  get isConnected(): boolean {
    return this._state === 'connected';
  }

  // --- Service Accessors ---

  /** Tree state service (sessions, turns, context modes) */
  get tree(): TreeStateServiceClient {
    if (!this._tree) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._tree;
  }

  /** Queue state service (message queues) */
  get queue(): QueueStateServiceClient {
    if (!this._queue) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._queue;
  }

  /** Session manager service (session lifecycle) */
  get sessions(): SessionManagerServiceClient {
    if (!this._sessions) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._sessions;
  }

  /** Goal tree state service (goals, plans, todos) */
  get goals(): GoalTreeStateServiceClient {
    if (!this._goals) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._goals;
  }

  /** Task state service (LLM task lifecycle) */
  get tasks(): TaskStateServiceClient {
    if (!this._tasks) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._tasks;
  }

  // --- Connection Management ---

  /**
   * Connect to the Balloons backend.
   *
   * @returns Promise that resolves when connected
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this._state === 'connected') {
        resolve();
        return;
      }

      this.setState('connecting');

      // Build URL with token if provided
      let connectUrl = this.url;
      if (this.options.token) {
        const separator = connectUrl.includes('?') ? '&' : '?';
        connectUrl += `${separator}token=${encodeURIComponent(this.options.token)}`;
      }

      this.ws = new WebSocket(connectUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.initializeClients();
        this.setState('connected');
        resolve();
      };

      this.ws.onerror = (event) => {
        console.error('WebSocket error:', event);
        this.setState('error');
      };

      this.ws.onclose = (event) => {
        this.clearClients();
        this.setState('disconnected');

        if (event.code === 4001) {
          // Authentication failed
          reject(new Error('Authentication failed'));
          return;
        }

        if (this.options.autoReconnect && this.reconnectAttempts < this.options.maxReconnectAttempts) {
          this.scheduleReconnect();
        }
      };
    });
  }

  /**
   * Disconnect from the backend.
   */
  disconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      // Disable auto-reconnect for intentional disconnect
      this.options.autoReconnect = false;
      this.ws.close();
      this.ws = null;
    }

    this.clearClients();
    this.setState('disconnected');
  }

  /**
   * Subscribe to connection state changes.
   *
   * @param listener Callback invoked when state changes
   * @returns Unsubscribe function
   */
  onStateChange(listener: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(listener);
    return () => {
      this.stateListeners.delete(listener);
    };
  }

  // --- Private Methods ---

  private setState(state: ConnectionState): void {
    if (this._state !== state) {
      this._state = state;
      this.stateListeners.forEach(listener => listener(state));
    }
  }

  private initializeClients(): void {
    if (!this.ws) return;

    this._tree = new TreeStateServiceClient(this.ws);
    this._queue = new QueueStateServiceClient(this.ws);
    this._sessions = new SessionManagerServiceClient(this.ws);
    this._goals = new GoalTreeStateServiceClient(this.ws);
    this._tasks = new TaskStateServiceClient(this.ws);
  }

  private clearClients(): void {
    this._tree = null;
    this._queue = null;
    this._sessions = null;
    this._goals = null;
    this._tasks = null;
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++;
    const delay = this.options.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.options.maxReconnectAttempts})`);

    this.reconnectTimer = setTimeout(() => {
      this.connect().catch(err => {
        console.error('Reconnection failed:', err);
      });
    }, delay) as unknown as number;
  }
}

// Re-export types for convenience
export * from './types';
export {
  TreeStateServiceClient,
  QueueStateServiceClient,
  SessionManagerServiceClient,
  GoalTreeStateServiceClient,
  TaskStateServiceClient,
  Unsubscribe,
} from './client';
