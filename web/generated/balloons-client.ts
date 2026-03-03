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
 *
 *   // Subscribe to session events and receive turns via historyChunk
 *   client.sessionData.subscribeSession(sessionId, clientId);
 *   client.sessionData.sessionDataHistoryChunk((chunk) => console.log('Turns:', chunk.turns));
 *   client.sessionData.sessionDataSessionUpdated((data) => console.log('Session:', data));
 *
 *   // Disconnect
 *   client.disconnect();
 */

import {
  QueueStateServiceClient,
  SessionManagerServiceClient,
  GoalTreeStateServiceClient,
  TaskStateServiceClient,
  SessionDataServiceClient,
  ImageServiceClient,
  SoundServiceClient,
  DebugLogServiceClient,
  FileStateServiceClient,
  SupervisorStateServiceClient,
  LSPServiceClient,
  KanbanWebSocketServiceClient,
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

  // Server-assigned client ID (received on connection)
  private _clientId: string | null = null;

  // Service clients (lazily initialized)
  private _queue: QueueStateServiceClient | null = null;
  private _sessions: SessionManagerServiceClient | null = null;
  private _goals: GoalTreeStateServiceClient | null = null;
  private _tasks: TaskStateServiceClient | null = null;
  private _sessionData: SessionDataServiceClient | null = null;
  private _images: ImageServiceClient | null = null;
  private _sounds: SoundServiceClient | null = null;
  private _debugLog: DebugLogServiceClient | null = null;
  private _files: FileStateServiceClient | null = null;
  private _supervisor: SupervisorStateServiceClient | null = null;
  private _lsp: LSPServiceClient | null = null;
  private _kanban: KanbanWebSocketServiceClient | null = null;

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

  /**
   * Get the server-assigned client ID.
   * This ID should be used for all subscription-related calls.
   * Only available after successful connection.
   */
  get clientId(): string {
    if (!this._clientId) {
      throw new Error('Not connected or clientId not yet received');
    }
    return this._clientId;
  }

  /** Check if clientId is available */
  get hasClientId(): boolean {
    return this._clientId !== null;
  }

  // --- Service Accessors ---

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

  /** Session data service (subscription-based streaming) */
  get sessionData(): SessionDataServiceClient {
    if (!this._sessionData) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._sessionData;
  }

  /** Image service (upload images for chat) */
  get images(): ImageServiceClient {
    if (!this._images) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._images;
  }

  /** Sound service (notification sounds) */
  get sounds(): SoundServiceClient {
    if (!this._sounds) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._sounds;
  }

  /** Debug log service (logging from web to TUI debug pane) */
  get debugLog(): DebugLogServiceClient {
    if (!this._debugLog) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._debugLog;
  }

  /** File state service (file browsing with git status) */
  get files(): FileStateServiceClient {
    if (!this._files) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._files;
  }

  /** Supervisor state service (hosts, processes, backends) */
  get supervisor(): SupervisorStateServiceClient {
    if (!this._supervisor) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._supervisor;
  }

  /** LSP service (language server management) */
  get lsp(): LSPServiceClient {
    if (!this._lsp) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._lsp;
  }

  /** Kanban service (boards, columns, tasks) */
  get kanban(): KanbanWebSocketServiceClient {
    if (!this._kanban) {
      throw new Error('Not connected. Call connect() first.');
    }
    return this._kanban;
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

      // Track whether we've received the clientId (needed to resolve connection)
      let clientIdReceived = false;
      let wsOpened = false;

      const maybeResolve = () => {
        if (clientIdReceived && wsOpened) {
          this.setState('connected');
          resolve();
        }
      };

      // Handle 'connected' event to receive server-assigned clientId
      // Using addEventListener so it doesn't interfere with service clients
      this.ws.addEventListener('message', (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.event === 'connected' && msg.data?.clientId) {
            this._clientId = msg.data.clientId;
            console.log('Server assigned clientId:', this._clientId);
            clientIdReceived = true;
            maybeResolve();
          }
        } catch {
          // Ignore parse errors - let service clients handle their events
        }
      });

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.initializeClients();
        wsOpened = true;
        maybeResolve();
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

    this._queue = new QueueStateServiceClient(this.ws);
    this._sessions = new SessionManagerServiceClient(this.ws);
    this._goals = new GoalTreeStateServiceClient(this.ws);
    this._tasks = new TaskStateServiceClient(this.ws);
    this._sessionData = new SessionDataServiceClient(this.ws);
    this._images = new ImageServiceClient(this.ws);
    this._sounds = new SoundServiceClient(this.ws);
    this._debugLog = new DebugLogServiceClient(this.ws);
    this._files = new FileStateServiceClient(this.ws);
    this._supervisor = new SupervisorStateServiceClient(this.ws);
    this._lsp = new LSPServiceClient(this.ws);
    this._kanban = new KanbanWebSocketServiceClient(this.ws);
  }

  private clearClients(): void {
    this._queue = null;
    this._sessions = null;
    this._goals = null;
    this._tasks = null;
    this._sessionData = null;
    this._images = null;
    this._sounds = null;
    this._debugLog = null;
    this._files = null;
    this._supervisor = null;
    this._lsp = null;
    this._kanban = null;
    this._clientId = null;
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
  QueueStateServiceClient,
  SessionManagerServiceClient,
  GoalTreeStateServiceClient,
  TaskStateServiceClient,
  SessionDataServiceClient,
  ImageServiceClient,
  SoundServiceClient,
  DebugLogServiceClient,
  FileStateServiceClient,
  SupervisorStateServiceClient,
  LSPServiceClient,
  KanbanWebSocketServiceClient,
} from './client';
export type { Unsubscribe } from './client';
