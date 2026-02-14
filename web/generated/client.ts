// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_event decorators.
// Generated: 2026-02-14T09:59:57.696507
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

/**
 * WebSocket-exposed service for queue state management.
 * 
 * Provides read/write access to message queues, pause/resume control,
 * and real-time event subscriptions for queue changes.
 */
export interface QueueStateService {
  /**
   * Add a message to a session's queue.
   * 
   * Args:
   * session_id: The session to add to
   * content: Message content
   * 
   * Returns:
   * The new message's ID
   */
  addMessage(sessionId: string, content: string): Promise<string>;

  /**
   * Clear all messages from a session's queue.
   * 
   * Args:
   * session_id: The session to clear
   * 
   * Returns:
   * Number of messages cleared
   */
  clear(sessionId: string): Promise<number>;

  /**
   * Remove and return content of messages up to first paused message.
   * 
   * This is called when streaming completes and queued messages should
   * be sent to the LLM.
   * 
   * Args:
   * session_id: The session to drain
   * 
   * Returns:
   * List of message content strings that were drained
   */
  drain(sessionId: string): Promise<string[]>;

  /**
   * Get the queue for the active session.
   * 
   * Returns:
   * Queue info if there's an active session, None otherwise
   */
  getActiveQueue(): Promise<Types.QueueInfo | null>;

  /**
   * Get the currently active session ID.
   * 
   * Returns:
   * Active session ID or null if no session is active
   */
  getActiveSessionId(): Promise<string | null>;

  /**
   * Get IDs of all sessions that have non-empty queues.
   * 
   * Returns:
   * List of session IDs with queued messages
   */
  getAllSessionsWithQueues(): Promise<string[]>;

  /**
   * Get number of messages in a session's queue.
   * 
   * Args:
   * session_id: The session ID
   * 
   * Returns:
   * Number of queued messages
   */
  getMessageCount(sessionId: string): Promise<number>;

  /**
   * Get the queue state for a session.
   * 
   * Args:
   * session_id: The session ID to get queue for
   * 
   * Returns:
   * Queue info (may be empty if session has no queued messages)
   */
  getQueue(sessionId: string): Promise<Types.QueueInfo>;

  /**
   * Check if a session has any queued messages.
   * 
   * Args:
   * session_id: The session ID
   * 
   * Returns:
   * True if session has queued messages
   */
  hasMessages(sessionId: string): Promise<boolean>;

  /**
   * Check if a session's queue is blocked (first message paused).
   * 
   * Args:
   * session_id: The session to check
   * 
   * Returns:
   * True if queue is blocked
   */
  isBlocked(sessionId: string): Promise<boolean>;

  /**
   * Remove a message from a session's queue.
   * 
   * Args:
   * session_id: The session to remove from
   * message_id: ID of message to remove
   * 
   * Returns:
   * True if message was found and removed
   */
  removeMessage(sessionId: string, messageId: string): Promise<boolean>;

  /**
   * Set the currently active session.
   * 
   * Args:
   * session_id: The active session ID, or null for no active session
   */
  setActiveSession(sessionId: string | null): Promise<null>;

  /**
   * Toggle the paused state of a message.
   * 
   * Args:
   * session_id: The session containing the message
   * message_id: ID of message to toggle
   * 
   * Returns:
   * New paused state, or null if message not found
   */
  togglePause(sessionId: string, messageId: string): Promise<boolean | null>;

  /**
   * Update a message's content.
   * 
   * Args:
   * session_id: The session containing the message
   * message_id: ID of message to update
   * content: New content
   * 
   * Returns:
   * True if message was found and updated
   */
  updateContent(sessionId: string, messageId: string, content: string): Promise<boolean>;

}

export interface QueueStateEvents {
  /**
   * Emitted when a complete state rebuild is needed.
   */
  onFullRebuild(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when a message is added to a queue.
   */
  onMessageAdded(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when a message is removed from a queue.
   */
  onMessageRemoved(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when a message's content is updated.
   */
  onMessageUpdated(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when a message's pause state is toggled.
   */
  onPauseToggled(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when a queue is cleared.
   */
  onQueueCleared(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when messages are drained from a queue.
   */
  onQueueDrained(callback: (data: Types.QueueEventData) => void): Unsubscribe;

  /**
   * Emitted when the active session changes.
   */
  onSessionChanged(callback: (data: Types.QueueEventData) => void): Unsubscribe;

}

export class QueueStateServiceClient implements QueueStateService {
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

  async addMessage(sessionId: string, content: string): Promise<string> {
    return this.call('addMessage', { sessionId: sessionId, content: content });
  }

  async clear(sessionId: string): Promise<number> {
    return this.call('clear', { sessionId: sessionId });
  }

  async drain(sessionId: string): Promise<string[]> {
    return this.call('drain', { sessionId: sessionId });
  }

  async getActiveQueue(): Promise<Types.QueueInfo | null> {
    return this.call('getActiveQueue', {  });
  }

  async getActiveSessionId(): Promise<string | null> {
    return this.call('getActiveSessionId', {  });
  }

  async getAllSessionsWithQueues(): Promise<string[]> {
    return this.call('getAllSessionsWithQueues', {  });
  }

  async getMessageCount(sessionId: string): Promise<number> {
    return this.call('getMessageCount', { sessionId: sessionId });
  }

  async getQueue(sessionId: string): Promise<Types.QueueInfo> {
    return this.call('getQueue', { sessionId: sessionId });
  }

  async hasMessages(sessionId: string): Promise<boolean> {
    return this.call('hasMessages', { sessionId: sessionId });
  }

  async isBlocked(sessionId: string): Promise<boolean> {
    return this.call('isBlocked', { sessionId: sessionId });
  }

  async removeMessage(sessionId: string, messageId: string): Promise<boolean> {
    return this.call('removeMessage', { sessionId: sessionId, messageId: messageId });
  }

  async setActiveSession(sessionId: string | null): Promise<null> {
    return this.call('setActiveSession', { sessionId: sessionId });
  }

  async togglePause(sessionId: string, messageId: string): Promise<boolean | null> {
    return this.call('togglePause', { sessionId: sessionId, messageId: messageId });
  }

  async updateContent(sessionId: string, messageId: string, content: string): Promise<boolean> {
    return this.call('updateContent', { sessionId: sessionId, messageId: messageId, content: content });
  }

  onFullRebuild(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onFullRebuild', callback);
  }

  onMessageAdded(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onMessageAdded', callback);
  }

  onMessageRemoved(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onMessageRemoved', callback);
  }

  onMessageUpdated(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onMessageUpdated', callback);
  }

  onPauseToggled(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onPauseToggled', callback);
  }

  onQueueCleared(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onQueueCleared', callback);
  }

  onQueueDrained(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onQueueDrained', callback);
  }

  onSessionChanged(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('onSessionChanged', callback);
  }

}

/**
 * WebSocket-exposed service for session lifecycle management.
 * 
 * Provides operations for creating, switching, listing, and deleting sessions.
 * Also exposes streaming status for all sessions.
 */
export interface SessionManagerService {
  /**
   * Cancel streaming for a session.
   * 
   * Args:
   * session_id: ID of the session to cancel
   * 
   * Returns:
   * True if streaming was cancelled, False if session wasn't streaming
   */
  cancelStreaming(sessionId: string): Promise<boolean>;

  /**
   * Create a new session.
   * 
   * Args:
   * working_directory: Initial working directory (defaults to cwd)
   * 
   * Returns:
   * Info about the created session
   */
  createSession(workingDirectory?: string | null): Promise<Types.ManagedSessionInfo>;

  /**
   * Delete a session.
   * 
   * Note: This removes the session from memory and storage.
   * If the deleted session was active, no session will be active after.
   * 
   * Args:
   * session_id: ID of the session to delete
   * 
   * Returns:
   * True if session was deleted, False if not found
   */
  deleteSession(sessionId: string): Promise<boolean>;

  /**
   * Get the ID of the currently active session.
   * 
   * Returns:
   * Active session ID, or None if no session is active
   */
  getActiveSessionId(): Promise<string | null>;

  /**
   * Get streaming information for all active streams.
   * 
   * Returns:
   * List of streaming info for all active session streams
   */
  getAllStreamingInfo(): Promise<Types.StreamingInfo[]>;

  /**
   * Get information about a specific session.
   * 
   * Args:
   * session_id: ID of the session to get
   * 
   * Returns:
   * Session info, or None if not found
   */
  getSession(sessionId: string): Promise<Types.ManagedSessionInfo | null>;

  /**
   * Get streaming information for a session.
   * 
   * Args:
   * session_id: ID of the session to check
   * 
   * Returns:
   * Streaming info if session is streaming, None otherwise
   */
  getStreamingInfo(sessionId: string): Promise<Types.StreamingInfo | null>;

  /**
   * Get IDs of all sessions currently streaming.
   * 
   * Returns:
   * List of session IDs that are streaming
   */
  getStreamingSessions(): Promise<string[]>;

  /**
   * List all available sessions.
   * 
   * Returns:
   * List of session info objects
   */
  listSessions(): Promise<Types.ManagedSessionInfo[]>;

  /**
   * Switch to a different session.
   * 
   * Args:
   * session_id: ID of the session to switch to
   * 
   * Returns:
   * True if switch was successful, False if session not found
   */
  switchSession(sessionId: string): Promise<boolean>;

}

export interface SessionManagerEvents {
  /**
   * Emitted when a new session is created.
   */
  onSessionCreated(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is deleted.
   */
  onSessionDeleted(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when the active session changes.
   */
  onSessionSwitched(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when a session's metadata is updated.
   */
  onSessionUpdated(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when a session starts streaming.
   */
  onStreamingStarted(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when a session stops streaming.
   */
  onStreamingStopped(callback: (data: Types.SessionEventData) => void): Unsubscribe;

}

export class SessionManagerServiceClient implements SessionManagerService {
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

  async cancelStreaming(sessionId: string): Promise<boolean> {
    return this.call('cancelStreaming', { sessionId: sessionId });
  }

  async createSession(workingDirectory?: string | null): Promise<Types.ManagedSessionInfo> {
    return this.call('createSession', { workingDirectory: workingDirectory });
  }

  async deleteSession(sessionId: string): Promise<boolean> {
    return this.call('deleteSession', { sessionId: sessionId });
  }

  async getActiveSessionId(): Promise<string | null> {
    return this.call('getActiveSessionId', {  });
  }

  async getAllStreamingInfo(): Promise<Types.StreamingInfo[]> {
    return this.call('getAllStreamingInfo', {  });
  }

  async getSession(sessionId: string): Promise<Types.ManagedSessionInfo | null> {
    return this.call('getSession', { sessionId: sessionId });
  }

  async getStreamingInfo(sessionId: string): Promise<Types.StreamingInfo | null> {
    return this.call('getStreamingInfo', { sessionId: sessionId });
  }

  async getStreamingSessions(): Promise<string[]> {
    return this.call('getStreamingSessions', {  });
  }

  async listSessions(): Promise<Types.ManagedSessionInfo[]> {
    return this.call('listSessions', {  });
  }

  async switchSession(sessionId: string): Promise<boolean> {
    return this.call('switchSession', { sessionId: sessionId });
  }

  onSessionCreated(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('onSessionCreated', callback);
  }

  onSessionDeleted(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('onSessionDeleted', callback);
  }

  onSessionSwitched(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('onSessionSwitched', callback);
  }

  onSessionUpdated(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('onSessionUpdated', callback);
  }

  onStreamingStarted(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('onStreamingStarted', callback);
  }

  onStreamingStopped(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('onStreamingStopped', callback);
  }

}

/**
 * WebSocket-exposed service for goal tree state management.
 * 
 * Provides read/write access to goals, plans, todos, and session bindings,
 * with real-time event subscriptions for state changes.
 */
export interface GoalTreeStateService {
  /**
   * Add or update a goal.
   * 
   * Args:
   * goal: Goal data as dictionary (will be converted to GoalData)
   */
  addGoal(goal: Record<string, unknown>): Promise<null>;

  /**
   * Add or update a plan.
   * 
   * Args:
   * plan: Plan data as dictionary (will be converted to PlanData)
   */
  addPlan(plan: Record<string, unknown>): Promise<null>;

  /**
   * Add or update a todo.
   * 
   * Args:
   * todo: Todo data as dictionary (will be converted to TodoData)
   * plan_ids: Optional list of plan IDs to link the todo to
   */
  addTodo(todo: Record<string, unknown>, planIds?: string[] | null): Promise<null>;

  /**
   * Add a session to the unbound sessions list.
   * 
   * Args:
   * session_id: ID of the session
   * name: Display name for the session
   * token_count: Token count for the session
   * is_current: Whether this is the current session
   * is_streaming: Whether the session is streaming
   * fork_status: Fork status of the session
   */
  addUnboundSession(sessionId: string, name: string, tokenCount?: number, isCurrent?: boolean, isStreaming?: boolean, forkStatus?: string): Promise<null>;

  /**
   * Begin batch loading mode - suppress individual notifications.
   */
  beginBatchLoading(): Promise<null>;

  /**
   * Bind a session to an entity.
   * 
   * Args:
   * entity_type: Type of entity ("goal", "plan", "todo")
   * entity_id: ID of the entity
   * session_id: ID of the session to bind
   * name: Display name for the session
   * binding_role: Role of the binding (e.g., "implementation")
   * token_count: Token count for the session
   * is_current: Whether this is the current session
   * is_streaming: Whether the session is streaming
   * fork_status: Fork status of the session
   */
  bindSession(entityType: string, entityId: string, sessionId: string, name: string, bindingRole?: string, tokenCount?: number, isCurrent?: boolean, isStreaming?: boolean, forkStatus?: string): Promise<null>;

  /**
   * Clear all state.
   */
  clear(): Promise<null>;

  /**
   * End batch loading mode and trigger a full rebuild.
   */
  endBatchLoading(): Promise<null>;

  /**
   * Get all goals sorted by weight (descending).
   * 
   * Returns:
   * List of all goal info objects
   */
  getAllGoals(): Promise<Types.GoalInfo[]>;

  /**
   * Get sessions bound to an entity.
   * 
   * Args:
   * entity_id: ID of the entity
   * 
   * Returns:
   * List of session binding info objects
   */
  getBoundSessions(entityId: string): Promise<Types.SessionBindingInfo[]>;

  /**
   * Get child goals for a parent goal.
   * 
   * Args:
   * goal_id: The parent goal ID
   * 
   * Returns:
   * List of child goal info objects sorted by weight
   */
  getChildGoals(goalId: string): Promise<Types.GoalInfo[]>;

  /**
   * Get list of all collapsed node IDs.
   * 
   * Returns:
   * List of entity IDs that are collapsed
   */
  getCollapsedIds(): Promise<string[]>;

  /**
   * Get goal information by ID.
   * 
   * Args:
   * goal_id: The goal ID to look up
   * 
   * Returns:
   * Goal info if found, None otherwise
   */
  getGoal(goalId: string): Promise<Types.GoalInfo | null>;

  /**
   * Get progress for a goal.
   * 
   * Args:
   * goal_id: The goal ID
   * 
   * Returns:
   * Progress as (completed_todos, total_todos)
   */
  getGoalProgress(goalId: string): Promise<Types.GoalProgress>;

  /**
   * Get plan information by ID.
   * 
   * Args:
   * plan_id: The plan ID to look up
   * 
   * Returns:
   * Plan info if found, None otherwise
   */
  getPlan(planId: string): Promise<Types.PlanInfo | null>;

  /**
   * Get all plans for a goal.
   * 
   * Args:
   * goal_id: The parent goal ID
   * 
   * Returns:
   * List of plan info objects
   */
  getPlansForGoal(goalId: string): Promise<Types.PlanInfo[]>;

  /**
   * Get root-level goals (goals with no parent).
   * 
   * Returns:
   * List of root goal info objects sorted by weight
   */
  getRootGoals(): Promise<Types.GoalInfo[]>;

  /**
   * Get the currently selected entity.
   * 
   * Returns:
   * Selected entity info or None
   */
  getSelectedEntity(): Promise<Types.SelectedEntity | null>;

  /**
   * Get the entity a session is bound to.
   * 
   * Args:
   * session_id: ID of the session
   * 
   * Returns:
   * (entity_type, entity_id) tuple or None if unbound
   */
  getSessionBinding(sessionId: string): Promise<[string, string] | null>;

  /**
   * Get aggregate statistics for the tree.
   * 
   * Returns:
   * Statistics object
   */
  getStats(): Promise<Types.GoalTreeStats>;

  /**
   * Get todo information by ID.
   * 
   * Args:
   * todo_id: The todo ID to look up
   * 
   * Returns:
   * Todo info if found, None otherwise
   */
  getTodo(todoId: string): Promise<Types.TodoInfo | null>;

  /**
   * Get all todos for a plan.
   * 
   * Args:
   * plan_id: The parent plan ID
   * 
   * Returns:
   * List of todo info objects
   */
  getTodosForPlan(planId: string): Promise<Types.TodoInfo[]>;

  /**
   * Get all unbound sessions.
   * 
   * Returns:
   * List of session binding info objects
   */
  getUnboundSessions(): Promise<Types.SessionBindingInfo[]>;

  /**
   * Check if a node is collapsed.
   * 
   * Args:
   * entity_id: ID of the entity
   * 
   * Returns:
   * True if collapsed, False otherwise
   */
  isCollapsed(entityId: string): Promise<boolean>;

  /**
   * Check if a session is bound to any entity.
   * 
   * Args:
   * session_id: ID of the session
   * 
   * Returns:
   * True if bound, False otherwise
   */
  isSessionBound(sessionId: string): Promise<boolean>;

  /**
   * Remove a goal and its children.
   * 
   * Args:
   * goal_id: The goal ID to remove
   */
  removeGoal(goalId: string): Promise<null>;

  /**
   * Remove a plan.
   * 
   * Args:
   * plan_id: The plan ID to remove
   */
  removePlan(planId: string): Promise<null>;

  /**
   * Remove a todo.
   * 
   * Args:
   * todo_id: The todo ID to remove
   */
  removeTodo(todoId: string): Promise<null>;

  /**
   * Remove a session from the unbound sessions list.
   * 
   * Args:
   * session_id: ID of the session to remove
   */
  removeUnboundSession(sessionId: string): Promise<null>;

  /**
   * Request that all observers rebuild their views.
   */
  requestRebuild(): Promise<null>;

  /**
   * Select an entity in the tree.
   * 
   * Args:
   * entity_type: Type of entity ("goal", "plan", "todo", "session")
   * entity_id: ID of the entity
   */
  selectEntity(entityType: string, entityId: string): Promise<null>;

  /**
   * Set the collapsed state of a node.
   * 
   * Args:
   * entity_id: ID of the entity
   * collapsed: True to collapse, False to expand
   */
  setCollapsed(entityId: string, collapsed: boolean): Promise<null>;

  /**
   * Set the collapsed node IDs.
   * 
   * Args:
   * collapsed_ids: List of entity IDs that should be collapsed
   */
  setCollapsedIds(collapsedIds: string[]): Promise<null>;

  /**
   * Set the computed priority for a todo.
   * 
   * Args:
   * todo_id: The todo ID
   * priority: The priority value
   */
  setTodoPriority(todoId: string, priority: number): Promise<null>;

  /**
   * Toggle the collapsed state of a node.
   * 
   * Args:
   * entity_id: ID of the entity
   * 
   * Returns:
   * The new collapsed state
   */
  toggleCollapsed(entityId: string): Promise<boolean>;

  /**
   * Unbind a session from an entity.
   * 
   * Args:
   * entity_id: ID of the entity
   * session_id: ID of the session to unbind
   */
  unbindSession(entityId: string, sessionId: string): Promise<null>;

}

export interface GoalTreeStateEvents {
  /**
   * Emitted when an entity is selected.
   */
  onEntitySelected(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a full rebuild is requested.
   */
  onFullRebuild(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a goal is added.
   */
  onGoalAdded(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a goal is removed.
   */
  onGoalRemoved(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a goal is updated.
   */
  onGoalUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a plan is added.
   */
  onPlanAdded(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a plan is removed.
   */
  onPlanRemoved(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a plan is updated.
   */
  onPlanUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is bound to an entity.
   */
  onSessionBound(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is unbound from an entity.
   */
  onSessionUnbound(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a session's metadata changes.
   */
  onSessionUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a todo is added.
   */
  onTodoAdded(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a todo is removed.
   */
  onTodoRemoved(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

  /**
   * Emitted when a todo is updated.
   */
  onTodoUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe;

}

export class GoalTreeStateServiceClient implements GoalTreeStateService {
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

  async addGoal(goal: Record<string, unknown>): Promise<null> {
    return this.call('addGoal', { goal: goal });
  }

  async addPlan(plan: Record<string, unknown>): Promise<null> {
    return this.call('addPlan', { plan: plan });
  }

  async addTodo(todo: Record<string, unknown>, planIds?: string[] | null): Promise<null> {
    return this.call('addTodo', { todo: todo, planIds: planIds });
  }

  async addUnboundSession(sessionId: string, name: string, tokenCount?: number, isCurrent?: boolean, isStreaming?: boolean, forkStatus?: string): Promise<null> {
    return this.call('addUnboundSession', { sessionId: sessionId, name: name, tokenCount: tokenCount, isCurrent: isCurrent, isStreaming: isStreaming, forkStatus: forkStatus });
  }

  async beginBatchLoading(): Promise<null> {
    return this.call('beginBatchLoading', {  });
  }

  async bindSession(entityType: string, entityId: string, sessionId: string, name: string, bindingRole?: string, tokenCount?: number, isCurrent?: boolean, isStreaming?: boolean, forkStatus?: string): Promise<null> {
    return this.call('bindSession', { entityType: entityType, entityId: entityId, sessionId: sessionId, name: name, bindingRole: bindingRole, tokenCount: tokenCount, isCurrent: isCurrent, isStreaming: isStreaming, forkStatus: forkStatus });
  }

  async clear(): Promise<null> {
    return this.call('clear', {  });
  }

  async endBatchLoading(): Promise<null> {
    return this.call('endBatchLoading', {  });
  }

  async getAllGoals(): Promise<Types.GoalInfo[]> {
    return this.call('getAllGoals', {  });
  }

  async getBoundSessions(entityId: string): Promise<Types.SessionBindingInfo[]> {
    return this.call('getBoundSessions', { entityId: entityId });
  }

  async getChildGoals(goalId: string): Promise<Types.GoalInfo[]> {
    return this.call('getChildGoals', { goalId: goalId });
  }

  async getCollapsedIds(): Promise<string[]> {
    return this.call('getCollapsedIds', {  });
  }

  async getGoal(goalId: string): Promise<Types.GoalInfo | null> {
    return this.call('getGoal', { goalId: goalId });
  }

  async getGoalProgress(goalId: string): Promise<Types.GoalProgress> {
    return this.call('getGoalProgress', { goalId: goalId });
  }

  async getPlan(planId: string): Promise<Types.PlanInfo | null> {
    return this.call('getPlan', { planId: planId });
  }

  async getPlansForGoal(goalId: string): Promise<Types.PlanInfo[]> {
    return this.call('getPlansForGoal', { goalId: goalId });
  }

  async getRootGoals(): Promise<Types.GoalInfo[]> {
    return this.call('getRootGoals', {  });
  }

  async getSelectedEntity(): Promise<Types.SelectedEntity | null> {
    return this.call('getSelectedEntity', {  });
  }

  async getSessionBinding(sessionId: string): Promise<[string, string] | null> {
    return this.call('getSessionBinding', { sessionId: sessionId });
  }

  async getStats(): Promise<Types.GoalTreeStats> {
    return this.call('getStats', {  });
  }

  async getTodo(todoId: string): Promise<Types.TodoInfo | null> {
    return this.call('getTodo', { todoId: todoId });
  }

  async getTodosForPlan(planId: string): Promise<Types.TodoInfo[]> {
    return this.call('getTodosForPlan', { planId: planId });
  }

  async getUnboundSessions(): Promise<Types.SessionBindingInfo[]> {
    return this.call('getUnboundSessions', {  });
  }

  async isCollapsed(entityId: string): Promise<boolean> {
    return this.call('isCollapsed', { entityId: entityId });
  }

  async isSessionBound(sessionId: string): Promise<boolean> {
    return this.call('isSessionBound', { sessionId: sessionId });
  }

  async removeGoal(goalId: string): Promise<null> {
    return this.call('removeGoal', { goalId: goalId });
  }

  async removePlan(planId: string): Promise<null> {
    return this.call('removePlan', { planId: planId });
  }

  async removeTodo(todoId: string): Promise<null> {
    return this.call('removeTodo', { todoId: todoId });
  }

  async removeUnboundSession(sessionId: string): Promise<null> {
    return this.call('removeUnboundSession', { sessionId: sessionId });
  }

  async requestRebuild(): Promise<null> {
    return this.call('requestRebuild', {  });
  }

  async selectEntity(entityType: string, entityId: string): Promise<null> {
    return this.call('selectEntity', { entityType: entityType, entityId: entityId });
  }

  async setCollapsed(entityId: string, collapsed: boolean): Promise<null> {
    return this.call('setCollapsed', { entityId: entityId, collapsed: collapsed });
  }

  async setCollapsedIds(collapsedIds: string[]): Promise<null> {
    return this.call('setCollapsedIds', { collapsedIds: collapsedIds });
  }

  async setTodoPriority(todoId: string, priority: number): Promise<null> {
    return this.call('setTodoPriority', { todoId: todoId, priority: priority });
  }

  async toggleCollapsed(entityId: string): Promise<boolean> {
    return this.call('toggleCollapsed', { entityId: entityId });
  }

  async unbindSession(entityId: string, sessionId: string): Promise<null> {
    return this.call('unbindSession', { entityId: entityId, sessionId: sessionId });
  }

  onEntitySelected(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onEntitySelected', callback);
  }

  onFullRebuild(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onFullRebuild', callback);
  }

  onGoalAdded(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onGoalAdded', callback);
  }

  onGoalRemoved(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onGoalRemoved', callback);
  }

  onGoalUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onGoalUpdated', callback);
  }

  onPlanAdded(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onPlanAdded', callback);
  }

  onPlanRemoved(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onPlanRemoved', callback);
  }

  onPlanUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onPlanUpdated', callback);
  }

  onSessionBound(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionBound', callback);
  }

  onSessionUnbound(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionUnbound', callback);
  }

  onSessionUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onSessionUpdated', callback);
  }

  onTodoAdded(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onTodoAdded', callback);
  }

  onTodoRemoved(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onTodoRemoved', callback);
  }

  onTodoUpdated(callback: (data: Types.GoalTreeEventData) => void): Unsubscribe {
    return this.subscribe('onTodoUpdated', callback);
  }

}

/**
 * WebSocket-exposed service for task state management.
 * 
 * Provides access to LLM task lifecycle information including:
 * - Active and completed tasks
 * - Task status updates (streaming, executing, completed, error)
 * - Session-level task summaries
 * - Backend usage statistics
 * 
 * All tasks are in-memory only and are not persisted across restarts.
 */
export interface TaskStateService {
  /**
   * Mark a task as cancelled by user.
   * 
   * Args:
   * task_id: Task to cancel
   * 
   * Returns:
   * Cancelled task info, or None if task not found
   */
  cancelTask(taskId: string): Promise<Types.TaskInfo | null>;

  /**
   * Remove completed tasks older than max_age_seconds.
   * 
   * Args:
   * max_age_seconds: Maximum age in seconds to keep completed tasks
   * 
   * Returns:
   * Number of tasks removed
   */
  clearCompleted(maxAgeSeconds?: number): Promise<number>;

  /**
   * Mark a task as completed successfully.
   * 
   * Args:
   * task_id: Task to complete
   * 
   * Returns:
   * Completed task info, or None if task not found
   */
  completeTask(taskId: string): Promise<Types.TaskInfo | null>;

  /**
   * Mark a task as failed with an error.
   * 
   * Args:
   * task_id: Task that failed
   * error: Error message
   * 
   * Returns:
   * Failed task info, or None if task not found
   */
  failTask(taskId: string, error: string): Promise<Types.TaskInfo | null>;

  /**
   * Get count of all active tasks.
   * 
   * Returns:
   * Number of active tasks (pending, streaming, executing)
   */
  getActiveCount(): Promise<number>;

  /**
   * Get all active tasks (pending, streaming, or executing).
   * 
   * Returns:
   * List of active tasks
   */
  getActiveTasks(): Promise<Types.TaskInfo[]>;

  /**
   * Get all tracked tasks (active and recent).
   * 
   * Returns:
   * List of all tasks, sorted by start time (newest first)
   */
  getAllTasks(): Promise<Types.TaskInfo[]>;

  /**
   * Get count of active tasks per backend.
   * 
   * Returns:
   * List of backend summaries with active task counts
   */
  getBackendSummary(): Promise<Types.BackendSummary[]>;

  /**
   * Get task summary for a session.
   * 
   * Args:
   * session_id: Session to summarize
   * 
   * Returns:
   * Session task summary with current state
   */
  getSessionSummary(sessionId: string): Promise<Types.SessionTaskSummary>;

  /**
   * Get the current active task for a session.
   * 
   * Args:
   * session_id: The session ID to look up
   * 
   * Returns:
   * Current active task info, or None if no active task
   */
  getSessionTask(sessionId: string): Promise<Types.TaskInfo | null>;

  /**
   * Get count of tasks currently streaming.
   * 
   * Returns:
   * Number of tasks with STREAMING status
   */
  getStreamingCount(): Promise<number>;

  /**
   * Get all tasks currently streaming.
   * 
   * Returns:
   * List of tasks with STREAMING status
   */
  getStreamingTasks(): Promise<Types.TaskInfo[]>;

  /**
   * Get a task by ID.
   * 
   * Args:
   * task_id: The task ID to look up
   * 
   * Returns:
   * Task info if found, None otherwise
   */
  getTask(taskId: string): Promise<Types.TaskInfo | null>;

  /**
   * Get all active tasks using a specific backend.
   * 
   * Args:
   * backend_name: Backend to filter by (e.g., "claude", "openrouter")
   * 
   * Returns:
   * List of active tasks using that backend
   */
  getTasksByBackend(backendName: string): Promise<Types.TaskInfo[]>;

  /**
   * Get all tasks for a session (active and completed).
   * 
   * Args:
   * session_id: Session ID to look up
   * 
   * Returns:
   * List of tasks for the session
   */
  getTasksBySession(sessionId: string): Promise<Types.TaskInfo[]>;

  /**
   * Get all tasks of a specific type.
   * 
   * Args:
   * task_type: Task type string (chat, compression, merge, link, archive, title, report)
   * 
   * Returns:
   * List of matching tasks
   */
  getTasksByType(taskType: string): Promise<Types.TaskInfo[]>;

  /**
   * Mark a task as executing a tool.
   * 
   * Args:
   * task_id: Task that is executing
   * tool_name: Name of the tool being executed
   * 
   * Returns:
   * Updated task info, or None if task not found
   */
  setTaskExecuting(taskId: string, toolName: string): Promise<Types.TaskInfo | null>;

  /**
   * Mark a task as streaming (back from tool execution).
   * 
   * Args:
   * task_id: Task that is streaming
   * 
   * Returns:
   * Updated task info, or None if task not found
   */
  setTaskStreaming(taskId: string): Promise<Types.TaskInfo | null>;

  /**
   * Register a helper task (compression, summary, etc.).
   * 
   * Args:
   * task_id: Unique ID for this task
   * task_type: Type of helper task (compression, merge, link, archive, title, report)
   * prompt: Description of what's being done
   * session_id: Associated session (if any)
   * backend_name: Which backend is handling this
   * 
   * Returns:
   * The created task info, or None if invalid task_type
   */
  startHelperTask(taskId: string, taskType: string, prompt?: string, sessionId?: string | null, backendName?: string): Promise<Types.TaskInfo | null>;

  /**
   * Register a new chat task for a session.
   * 
   * Args:
   * session_id: The session this task belongs to
   * exchange_id: Unique ID for this exchange (used as task_id)
   * prompt: The user's prompt
   * backend_name: Which backend is handling this
   * 
   * Returns:
   * The created task info
   */
  startSessionTask(sessionId: string, exchangeId: string, prompt: string, backendName?: string): Promise<Types.TaskInfo>;

  /**
   * Update a task's progress (tokens, tool execution, etc.).
   * 
   * Args:
   * task_id: Task to update
   * tokens_streamed: Updated estimated token count
   * tool_name: Currently executing tool name
   * tool_count: Updated tool count
   * input_tokens: Actual input token count from API
   * output_tokens: Actual output token count from API
   * context_window: Model's context window size
   * model: Model name
   * 
   * Returns:
   * Updated task info, or None if task not found
   */
  updateTaskProgress(taskId: string, tokensStreamed?: number | null, toolName?: string | null, toolCount?: number | null, inputTokens?: number | null, outputTokens?: number | null, contextWindow?: number | null, model?: string | null): Promise<Types.TaskInfo | null>;

}

export interface TaskStateEvents {
  /**
   * Emitted when a task is cancelled by the user.
   */
  onTaskCancelled(callback: (data: Types.TaskEventData) => void): Unsubscribe;

  /**
   * Emitted when a task completes successfully.
   */
  onTaskCompleted(callback: (data: Types.TaskEventData) => void): Unsubscribe;

  /**
   * Emitted when a task fails with an error.
   */
  onTaskError(callback: (data: Types.TaskEventData) => void): Unsubscribe;

  /**
   * Emitted when a new task starts.
   */
  onTaskStarted(callback: (data: Types.TaskEventData) => void): Unsubscribe;

  /**
   * Emitted when a task's status or progress changes.
   */
  onTaskUpdated(callback: (data: Types.TaskEventData) => void): Unsubscribe;

}

export class TaskStateServiceClient implements TaskStateService {
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

  async cancelTask(taskId: string): Promise<Types.TaskInfo | null> {
    return this.call('cancelTask', { taskId: taskId });
  }

  async clearCompleted(maxAgeSeconds?: number): Promise<number> {
    return this.call('clearCompleted', { maxAgeSeconds: maxAgeSeconds });
  }

  async completeTask(taskId: string): Promise<Types.TaskInfo | null> {
    return this.call('completeTask', { taskId: taskId });
  }

  async failTask(taskId: string, error: string): Promise<Types.TaskInfo | null> {
    return this.call('failTask', { taskId: taskId, error: error });
  }

  async getActiveCount(): Promise<number> {
    return this.call('getActiveCount', {  });
  }

  async getActiveTasks(): Promise<Types.TaskInfo[]> {
    return this.call('getActiveTasks', {  });
  }

  async getAllTasks(): Promise<Types.TaskInfo[]> {
    return this.call('getAllTasks', {  });
  }

  async getBackendSummary(): Promise<Types.BackendSummary[]> {
    return this.call('getBackendSummary', {  });
  }

  async getSessionSummary(sessionId: string): Promise<Types.SessionTaskSummary> {
    return this.call('getSessionSummary', { sessionId: sessionId });
  }

  async getSessionTask(sessionId: string): Promise<Types.TaskInfo | null> {
    return this.call('getSessionTask', { sessionId: sessionId });
  }

  async getStreamingCount(): Promise<number> {
    return this.call('getStreamingCount', {  });
  }

  async getStreamingTasks(): Promise<Types.TaskInfo[]> {
    return this.call('getStreamingTasks', {  });
  }

  async getTask(taskId: string): Promise<Types.TaskInfo | null> {
    return this.call('getTask', { taskId: taskId });
  }

  async getTasksByBackend(backendName: string): Promise<Types.TaskInfo[]> {
    return this.call('getTasksByBackend', { backendName: backendName });
  }

  async getTasksBySession(sessionId: string): Promise<Types.TaskInfo[]> {
    return this.call('getTasksBySession', { sessionId: sessionId });
  }

  async getTasksByType(taskType: string): Promise<Types.TaskInfo[]> {
    return this.call('getTasksByType', { taskType: taskType });
  }

  async setTaskExecuting(taskId: string, toolName: string): Promise<Types.TaskInfo | null> {
    return this.call('setTaskExecuting', { taskId: taskId, toolName: toolName });
  }

  async setTaskStreaming(taskId: string): Promise<Types.TaskInfo | null> {
    return this.call('setTaskStreaming', { taskId: taskId });
  }

  async startHelperTask(taskId: string, taskType: string, prompt?: string, sessionId?: string | null, backendName?: string): Promise<Types.TaskInfo | null> {
    return this.call('startHelperTask', { taskId: taskId, taskType: taskType, prompt: prompt, sessionId: sessionId, backendName: backendName });
  }

  async startSessionTask(sessionId: string, exchangeId: string, prompt: string, backendName?: string): Promise<Types.TaskInfo> {
    return this.call('startSessionTask', { sessionId: sessionId, exchangeId: exchangeId, prompt: prompt, backendName: backendName });
  }

  async updateTaskProgress(taskId: string, tokensStreamed?: number | null, toolName?: string | null, toolCount?: number | null, inputTokens?: number | null, outputTokens?: number | null, contextWindow?: number | null, model?: string | null): Promise<Types.TaskInfo | null> {
    return this.call('updateTaskProgress', { taskId: taskId, tokensStreamed: tokensStreamed, toolName: toolName, toolCount: toolCount, inputTokens: inputTokens, outputTokens: outputTokens, contextWindow: contextWindow, model: model });
  }

  onTaskCancelled(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('onTaskCancelled', callback);
  }

  onTaskCompleted(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('onTaskCompleted', callback);
  }

  onTaskError(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('onTaskError', callback);
  }

  onTaskStarted(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('onTaskStarted', callback);
  }

  onTaskUpdated(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('onTaskUpdated', callback);
  }

}

