// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_event decorators.
// Generated: 2026-02-10T07:52:59.260641
//
// To regenerate:
//     python -m codegen.generate_typescript
//
// To add new methods/events, add @ws_expose/@ws_event decorators in service modules.

import type * as Types from './types';

export type Unsubscribe = () => void;

/**
 * WebSocket-exposed service for tree state management.
 * 
 * Provides read/write access to session and turn data, context mode management,
 * and real-time event subscriptions for state changes.
 */
export interface TreeStateService {
  /**
   * Get all sessions.
   * 
   * Returns:
   * List of all session info objects
   */
  getAllSessions(): Promise<Types.SessionInfo[]>;

  /**
   * Get the context mode for a turn.
   * 
   * Args:
   * session_id: The session ID
   * turn_idx: The turn index
   * 
   * Returns:
   * Context mode string: "copy", "compress", or "drop"
   */
  getContextMode(sessionId: string, turnIdx: number): Promise<string>;

  /**
   * Get current context token counts.
   * 
   * Returns:
   * Tuple of (selected_tokens, total_tokens)
   */
  getContextTokens(): Promise<[number, number]>;

  /**
   * Get the current active session ID.
   * 
   * Returns:
   * Current session ID or None if no session is active
   */
  getCurrentSessionId(): Promise<string | null>;

  /**
   * Get session information by ID.
   * 
   * Args:
   * session_id: The session ID to look up
   * 
   * Returns:
   * Session info if found, None otherwise
   */
  getSession(sessionId: string): Promise<Types.SessionInfo | null>;

  /**
   * Get all session IDs that are currently streaming.
   * 
   * Returns:
   * List of streaming session IDs
   */
  getStreamingSessions(): Promise<string[]>;

  /**
   * Get a specific turn.
   * 
   * Args:
   * session_id: The session ID
   * turn_idx: The turn index
   * 
   * Returns:
   * Turn info if found, None otherwise
   */
  getTurn(sessionId: string, turnIdx: number): Promise<Types.TurnInfo | null>;

  /**
   * Get all turns for a session.
   * 
   * Args:
   * session_id: The session to get turns for
   * 
   * Returns:
   * List of turn info objects, empty if session not found/loaded
   */
  getTurns(sessionId: string): Promise<Types.TurnInfo[]>;

  /**
   * Get count of unviewed turns in a session.
   * 
   * Args:
   * session_id: The session ID
   * 
   * Returns:
   * Number of unviewed turns
   */
  getUnviewedCount(sessionId: string): Promise<number>;

  /**
   * Check if a session is currently streaming.
   * 
   * Args:
   * session_id: The session ID
   * 
   * Returns:
   * True if session is streaming
   */
  isStreaming(sessionId: string): Promise<boolean>;

  /**
   * Mark a turn as viewed.
   * 
   * Args:
   * session_id: The session ID
   * turn_idx: The turn index
   * 
   * Returns:
   * True if turn was marked viewed (was unviewed), False otherwise
   */
  markTurnViewed(sessionId: string, turnIdx: number): Promise<boolean>;

  /**
   * Set the context mode for a turn.
   * 
   * Args:
   * session_id: The session ID
   * turn_idx: The turn index
   * mode: The mode to set ("copy", "compress", or "drop")
   */
  setContextMode(sessionId: string, turnIdx: number, mode: string): Promise<null>;

  /**
   * Set the current active session.
   * 
   * Args:
   * session_id: The session to make current
   * 
   * Returns:
   * True if session was found and set, False otherwise
   */
  setCurrentSession(sessionId: string): Promise<boolean>;

  /**
   * Toggle context mode: COPY -> COMPRESS -> DROP -> COPY.
   * 
   * Args:
   * session_id: The session ID
   * turn_idx: The turn index
   * 
   * Returns:
   * The new context mode string
   */
  toggleContextMode(sessionId: string, turnIdx: number): Promise<string>;

}

export interface TreeStateEvents {
  /**
   * Emitted when a turn's context mode changes.
   */
  onContextModeChanged(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is added.
   */
  onSessionAdded(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is removed.
   */
  onSessionRemoved(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when the current session changes.
   */
  onSessionSelected(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is updated.
   */
  onSessionUpdated(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session starts streaming.
   */
  onStreamingStarted(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session stops streaming.
   */
  onStreamingStopped(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a turn finishes streaming.
   */
  onTurnFinished(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a new turn starts streaming.
   */
  onTurnStarted(callback: (data: Types.TreeEventData) => void): Unsubscribe;

  /**
   * Emitted when turn content is updated during streaming.
   */
  onTurnUpdated(callback: (data: Types.TreeEventData) => void): Unsubscribe;

}

export class TreeStateServiceClient implements TreeStateService {
  private ws: WebSocket;
  private pending: Map<string, { resolve: (v: any) => void; reject: (e: Error) => void }> = new Map();
  private eventHandlers: Map<string, Set<(data: any) => void>> = new Map();

  constructor(ws: WebSocket) {
    this.ws = ws;
    this.ws.addEventListener('message', this.handleMessage.bind(this));
  }

  private handleMessage(event: MessageEvent): void {
    const msg = JSON.parse(event.data);
    if (msg.id && this.pending.has(msg.id)) {
      const { resolve, reject } = this.pending.get(msg.id)!;
      this.pending.delete(msg.id);
      if (msg.error) {
        reject(new Error(msg.error.message));
      } else {
        resolve(msg.result);
      }
    } else if (msg.event) {
      const handlers = this.eventHandlers.get(msg.event);
      if (handlers) {
        handlers.forEach(h => h(msg.data));
      }
    }
  }

  private async call<T>(method: string, params: Record<string, unknown>): Promise<T> {
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  private subscribe(event: string, callback: (data: any) => void): Unsubscribe {
    if (!this.eventHandlers.has(event)) {
      this.eventHandlers.set(event, new Set());
    }
    this.eventHandlers.get(event)!.add(callback);
    return () => {
      this.eventHandlers.get(event)?.delete(callback);
    };
  }

  async getAllSessions(): Promise<Types.SessionInfo[]> {
    return this.call('getAllSessions', {  });
  }

  async getContextMode(sessionId: string, turnIdx: number): Promise<string> {
    return this.call('getContextMode', { sessionId: sessionId, turnIdx: turnIdx });
  }

  async getContextTokens(): Promise<[number, number]> {
    return this.call('getContextTokens', {  });
  }

  async getCurrentSessionId(): Promise<string | null> {
    return this.call('getCurrentSessionId', {  });
  }

  async getSession(sessionId: string): Promise<Types.SessionInfo | null> {
    return this.call('getSession', { sessionId: sessionId });
  }

  async getStreamingSessions(): Promise<string[]> {
    return this.call('getStreamingSessions', {  });
  }

  async getTurn(sessionId: string, turnIdx: number): Promise<Types.TurnInfo | null> {
    return this.call('getTurn', { sessionId: sessionId, turnIdx: turnIdx });
  }

  async getTurns(sessionId: string): Promise<Types.TurnInfo[]> {
    return this.call('getTurns', { sessionId: sessionId });
  }

  async getUnviewedCount(sessionId: string): Promise<number> {
    return this.call('getUnviewedCount', { sessionId: sessionId });
  }

  async isStreaming(sessionId: string): Promise<boolean> {
    return this.call('isStreaming', { sessionId: sessionId });
  }

  async markTurnViewed(sessionId: string, turnIdx: number): Promise<boolean> {
    return this.call('markTurnViewed', { sessionId: sessionId, turnIdx: turnIdx });
  }

  async setContextMode(sessionId: string, turnIdx: number, mode: string): Promise<null> {
    return this.call('setContextMode', { sessionId: sessionId, turnIdx: turnIdx, mode: mode });
  }

  async setCurrentSession(sessionId: string): Promise<boolean> {
    return this.call('setCurrentSession', { sessionId: sessionId });
  }

  async toggleContextMode(sessionId: string, turnIdx: number): Promise<string> {
    return this.call('toggleContextMode', { sessionId: sessionId, turnIdx: turnIdx });
  }

  onContextModeChanged(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onContextModeChanged', callback);
  }

  onSessionAdded(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionAdded', callback);
  }

  onSessionRemoved(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionRemoved', callback);
  }

  onSessionSelected(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionSelected', callback);
  }

  onSessionUpdated(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionUpdated', callback);
  }

  onStreamingStarted(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onStreamingStarted', callback);
  }

  onStreamingStopped(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onStreamingStopped', callback);
  }

  onTurnFinished(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onTurnFinished', callback);
  }

  onTurnStarted(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onTurnStarted', callback);
  }

  onTurnUpdated(callback: (data: Types.TreeEventData) => void): Unsubscribe {
    return this.subscribe('onTurnUpdated', callback);
  }

}

