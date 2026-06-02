// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_event decorators.
// Generated: 2026-06-01T14:31:38.529241
//
// To regenerate:
//     python -m codegen.generate_typescript
//
// To add new methods/events, add @ws_expose/@ws_event decorators in service modules.

import type * as Types from './types';

// Simple request ID generator for JSON-RPC correlation
let _requestId = 0;
function generateRequestId(): string {
  return String(++_requestId);
}

export type Unsubscribe = () => void;

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
    const id = generateRequestId();
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
    return this.subscribe('fullRebuild', callback);
  }

  onMessageAdded(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('messageAdded', callback);
  }

  onMessageRemoved(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('messageRemoved', callback);
  }

  onMessageUpdated(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('messageUpdated', callback);
  }

  onPauseToggled(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('pauseToggled', callback);
  }

  onQueueCleared(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('queueCleared', callback);
  }

  onQueueDrained(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('queueDrained', callback);
  }

  onSessionChanged(callback: (data: Types.QueueEventData) => void): Unsubscribe {
    return this.subscribe('sessionChanged', callback);
  }

}

/**
 * WebSocket-exposed service for session lifecycle management.
 * 
 * Provides operations for creating, switching, listing, and deleting sessions.
 * Also exposes streaming status for all sessions.
 * 
 * For frontend interaction, use submit_message() to send prompts and receive
 * streaming events via the wired TaskStateService. The event pump automatically
 * converts SessionRunner events to TaskStateService events.
 */
export interface SessionManagerService {
  /**
   * Add a file to be included in the system prompt for a session.
   * 
   * The file content will be loaded fresh each turn and included in the
   * system prompt.
   * 
   * Args:
   * session_id: Session to add the prompt file to
   * file_path: Absolute path to the file
   * 
   * Returns:
   * Dict with success status, error message if any, and updated file list
   */
  addSessionPromptFile(sessionId: string, filePath: string): Promise<Record<string, unknown>>;

  /**
   * Approve a session review and update the session title.
   * 
   * Args:
   * session_id: The session containing the review
   * summary_id: The ID of the SessionSummaryBlock to approve
   * approved_title: The final title (may differ from proposed)
   * edited_markdown: Optional edited markdown content
   * 
   * Returns:
   * ApproveSessionReviewResult with success status
   */
  approveSessionReview(sessionId: string, summaryId: string, approvedTitle: string, editedMarkdown?: string | null): Promise<Types.ApproveSessionReviewResult>;

  /**
   * Wait for a helper task to complete and return its result.
   * 
   * Polls the helper every 100ms until it completes or times out.
   * This is a convenience method for frontends that don't want to
   * handle helper events.
   * 
   * Args:
   * helper_id: ID of the helper to wait for
   * timeout_seconds: Maximum time to wait (default 30s)
   * 
   * Returns:
   * The helper's accumulated text result, or empty string on timeout/error
   */
  awaitHelperResult(helperId: string, timeoutSeconds?: number): Promise<string>;

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
   * Complete an archive after summary generation.
   * 
   * Can be called manually with a custom summary, or automatically
   * by the helper completion handler with the generated summary.
   * 
   * Args:
   * helper_id: ID of the archive helper task
   * summary: Summary text to use. If None, uses the helper's generated summary.
   * 
   * Returns:
   * CompleteArchiveResult with archive details
   */
  completeArchive(helperId: string, summary?: string | null): Promise<Types.CompleteArchiveResult>;

  /**
   * Complete a derive after context compression finishes.
   * 
   * Args:
   * helper_id: ID of the compression helper
   * compressed_summary: LLM-generated summary of compressed context
   * start_streaming: If True, start streaming after derive is ready
   * 
   * Returns:
   * DeriveSessionResult with the completed derive info
   */
  completeDeriveAfterCompression(helperId: string, compressedSummary: string, startStreaming?: boolean): Promise<Types.DeriveSessionResult>;

  /**
   * Complete a fork after context compression finishes.
   * 
   * Called when the compression helper completes. Inserts the summary
   * at the correct position and finalizes the fork.
   * 
   * Args:
   * helper_id: ID of the compression helper
   * compressed_summary: LLM-generated summary of compressed context
   * start_streaming: If True, start streaming after fork is ready
   * 
   * Returns:
   * ForkSessionResult with the completed fork info
   */
  completeForkAfterCompression(helperId: string, compressedSummary: string, startStreaming?: boolean): Promise<Types.ForkSessionResult>;

  /**
   * Complete a session review after LLM summary generation.
   * 
   * Called by the frontend after the helper runner finishes streaming
   * the review content.
   * 
   * Args:
   * helper_id: The helper ID from start_session_review
   * result_text: The accumulated LLM response text
   * 
   * Returns:
   * CompleteSessionReviewResult with the parsed review data
   */
  completeSessionReview(helperId: string, resultText: string): Promise<Types.CompleteSessionReviewResult>;

  /**
   * Mark a session as concluded.
   * 
   * Sets the concluded flag and adds a conclude turn to the conversation.
   * If no reason is provided, an auto-generated summary may be created.
   * 
   * Args:
   * session_id: ID of the session to conclude
   * reason: Optional reason/summary for concluding (auto-generated if empty)
   * 
   * Returns:
   * ConcludeSessionResult with conclusion info
   */
  concludeSession(sessionId: string, reason?: string): Promise<Types.ConcludeSessionResult>;

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
   * Create a watcher session to observe another session.
   * 
   * Deprecated convenience wrapper. Prefer creating a normal session and then
   * calling start_watching_session.
   */
  createWatcherSession(targetSessionId: string): Promise<Types.CreateWatcherSessionResult>;

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
   * Derive a new independent session from selected context.
   * 
   * Unlike fork, derive creates a session with no parent relationship.
   * The new session is completely independent.
   * 
   * Args:
   * source_session_id: ID of the session to derive from
   * prompt: Optional initial prompt for the derived session
   * context_modes: List of {turn_index, mode} dicts. Mode is "copy", "compress", or "drop".
   * If not provided, all turns are copied.
   * allowed_tools: List of tool names to allow, or None for all tools
   * start_streaming: If True and prompt provided, start streaming after creation
   * 
   * Returns:
   * DeriveSessionResult with new session info
   */
  deriveSession(sourceSessionId: string, prompt?: string, contextModes?: Record<string, unknown>[] | null, allowedTools?: string[] | null, startStreaming?: boolean): Promise<Types.DeriveSessionResult>;

  /**
   * Find a session to switch to.
   * 
   * Searches forks of current session, then parent's forks if in a fork.
   * 
   * Args:
   * session_id: Current session ID
   * name: Fork name or session ID prefix, or "parent"/".."
   * 
   * Returns:
   * SwitchTargetResult with target session or available forks
   */
  findSwitchTarget(sessionId: string, name: string): Promise<Types.SwitchTargetResult>;

  /**
   * Fork a new session from an existing parent session.
   * 
   * Creates a child session with selected context from the parent.
   * Context can be copied verbatim, compressed via LLM, or dropped.
   * 
   * If compression is needed, returns immediately with needs_compression=True
   * and helper_id. The client should then listen for helper events and call
   * complete_fork_after_compression() when done.
   * 
   * Args:
   * parent_session_id: ID of the session to fork from
   * prompt: Initial prompt for the fork
   * name: Optional name for the fork (e.g., "auth-bug")
   * background: If True, run in background and stay in parent session
   * context_modes: List of {turn_index, mode} dicts. Mode is "copy", "compress", or "drop".
   * auto_complete_compression: If True, automatically complete fork when compression
   * finishes (for clients that don't handle helper events).
   * If not provided, all turns are copied.
   * allowed_tools: List of tool names to allow, or None for all tools
   * start_streaming: If True, start streaming after fork creation. Set False
   * if you want to handle streaming separately.
   * backend_name: Backend/model to use for the fork. If empty, inherits from parent.
   * 
   * Returns:
   * ForkSessionResult with child session info and streaming state
   */
  forkSession(parentSessionId: string, prompt: string, name?: string, background?: boolean, contextModes?: Record<string, unknown>[] | null, allowedTools?: string[] | null, startStreaming?: boolean, autoCompleteCompression?: boolean, backendName?: string): Promise<Types.ForkSessionResult>;

  /**
   * Generate a commit message using the LLM.
   * 
   * Starts a background helper task to generate a commit message based on
   * the staged git diff. The helper_id can be used to track progress via
   * helper events (helperDelta, helperDone).
   * 
   * Args:
   * git_root: Path to the git repository root
   * staged_diff: The staged diff output (from git diff --cached)
   * 
   * Returns:
   * GenerateCommitMessageResult with helper_id for tracking progress
   */
  generateCommitMessage(gitRoot: string, stagedDiff: string): Promise<Types.GenerateCommitMessageResult>;

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
   * Get all available tools grouped by category.
   * 
   * This powers the Context tab tool list. It is primarily driven by tool-prompt
   * discovery (prompts/tools/*) plus a few hardcoded tool families that do not
   * participate in prompt-file discovery, such as core built-ins and currently
   * loaded domain plugin tools.
   * 
   * Returns:
   * Dict with categories mapping to tool lists, plus 'core', 'all', and
   * metadata distinguishing built-ins vs domain tools.
   */
  getAvailableTools(): Promise<Record<string, unknown>>;

  /**
   * Get the default enabled tools from config.
   * 
   * Returns:
   * List of default enabled tool names
   */
  getDefaultEnabledTools(): Promise<string[]>;

  /**
   * Get information about available and loaded domain plugins.
   * 
   * Returns:
   * Dict with:
   * - available: list of available domain IDs
   * - loaded: list of currently loaded domain IDs
   */
  getDomainInfo(): Promise<Record<string, unknown>>;

  /**
   * Get summaries of each exchange in a session for proposal UIs.
   * 
   * Returns short descriptions of each exchange for display in fork/merge
   * proposal components, helping the user understand what context each
   * exchange contains.
   * 
   * Args:
   * session_id: ID of the session to get exchange summaries for
   * exclude_current: If True, exclude the last exchange (the one
   * containing a proposal). Default True since this
   * is typically called when displaying a proposal.
   * 
   * Returns:
   * List of ExchangeSummary objects with index, summary, and default mode
   */
  getExchangeSummaries(sessionId: string, excludeCurrent?: boolean): Promise<Types.ExchangeSummary[]>;

  /**
   * Get a preview of the generated system prompt.
   * 
   * This allows the UI to show what prompt will be sent to the LLM based
   * on the currently enabled tools.
   * 
   * Args:
   * session_id: Optional session ID to get session-specific prompt
   * enabled_tools: Optional explicit list of tools to use (overrides session)
   * 
   * Returns:
   * Dict with 'prompt' (the generated prompt text) and 'length' (char count)
   */
  getPromptPreview(sessionId?: string | null, enabledTools?: string[] | null): Promise<Record<string, unknown>>;

  /**
   * Get a structured preview of the effective runner context for a session.
   */
  getRunnerContextPreview(sessionId: string, enabledTools?: string[] | null): Promise<Types.RunnerContextPreviewResult>;

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
   * Get the backend name for a session.
   * 
   * Args:
   * session_id: ID of the session
   * 
   * Returns:
   * Effective backend name (explicit or default), or None if session not found
   */
  getSessionBackend(sessionId: string): Promise<string | null>;

  /**
   * Get the enabled tools for a session.
   * 
   * Args:
   * session_id: ID of the session
   * 
   * Returns:
   * List of enabled tool names (or defaults if not explicitly set)
   */
  getSessionEnabledTools(sessionId: string): Promise<string[]>;

  /**
   * Get the list of prompt files for a session.
   * 
   * Args:
   * session_id: Session to get prompt files from
   * 
   * Returns:
   * Dict with prompt_files list
   */
  getSessionPromptFiles(sessionId: string): Promise<Record<string, unknown>>;

  /**
   * Get all reviews for a session.
   * 
   * Returns a list of review dictionaries with summary info for display
   * in the review history sidebar.
   * 
   * Args:
   * session_id: The session to get reviews for
   * 
   * Returns:
   * List of review dictionaries
   */
  getSessionReviews(sessionId: string): Promise<Record<string, unknown>[]>;

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
   * Get information about the system prompt components.
   * 
   * Returns details about each component of the system prompt including
   * token counts, for display in the Context tab's System Prompt section.
   * 
   * Args:
   * session_id: Optional session ID for context-specific info
   * 
   * Returns:
   * SystemPromptInfoResult with component information
   */
  getSystemPromptInfo(sessionId?: string | null): Promise<Types.SystemPromptInfoResult>;

  /**
   * Get a preview of the tool schemas that would be sent to OpenAI-compatible APIs.
   * 
   * This shows the JSON function definitions used for native function calling.
   * Only relevant for OpenAI-type backends (not Claude, which uses balloons-tool XML).
   * 
   * Includes:
   * - Core tools (Read, Write, Bash, etc.)
   * - Balloon tools (propose_fork, ask_user, etc.)
   * - Domain tools (from currently loaded domains like kanban, chess)
   * - Other enabled tool categories
   * 
   * Args:
   * session_id: Optional session ID to get session-specific tools
   * enabled_tools: Optional explicit list of tools to use (overrides session)
   * 
   * Returns:
   * Dict with 'schemas' (JSON array as string), 'tool_count', and 'length'
   */
  getToolSchemasPreview(sessionId?: string | null, enabledTools?: string[] | null): Promise<Record<string, unknown>>;

  /**
   * Create a bidirectional link between two sessions.
   * 
   * Links allow navigation between sessions without a parent/child relationship.
   * Both sessions get a LinkBlock turn pointing to the other.
   * 
   * Args:
   * source_session_id: The current session (where user initiated the link)
   * target_session_id: The session to link to
   * summary: Optional description of why these sessions are linked
   * 
   * Returns:
   * LinkSessionsResult with the shared link_id
   */
  linkSessions(sourceSessionId: string, targetSessionId: string, summary?: string): Promise<Types.LinkSessionsResult>;

  /**
   * List all available backend names.
   * 
   * Returns:
   * List of backend name strings
   */
  listBackends(): Promise<string[]>;

  /**
   * List all available sessions.
   * 
   * Returns:
   * List of session info objects
   */
  listSessions(): Promise<Types.ManagedSessionInfo[]>;

  /**
   * Load a domain plugin.
   * 
   * Args:
   * domain_id: ID of the domain to load (e.g., "chess")
   * session_id: Optional session to associate the domain with
   * 
   * Returns:
   * Dict with success status and error message if any
   */
  loadDomain(domainId: string, sessionId?: string | null): Promise<Record<string, unknown>>;

  /**
   * Merge a fork session back to its parent.
   * 
   * Creates a merge marker in both the fork and parent sessions,
   * recording what was accomplished in the fork.
   * 
   * Args:
   * fork_session_id: ID of the fork session to merge
   * merge_summary: Summary of what was accomplished in the fork
   * files_changed: List of key files that were modified
   * key_accomplishments: List of what was done
   * reason: Why the merge is happening now
   * 
   * Returns:
   * MergeSessionResult with merge info
   */
  mergeSession(forkSessionId: string, mergeSummary: string, filesChanged?: string[] | null, keyAccomplishments?: string[] | null, reason?: string): Promise<Types.MergeSessionResult>;

  /**
   * Restore archived turns back into the conversation.
   * 
   * Replaces the archive marker with the original messages.
   * 
   * Args:
   * session_id: ID of the session containing the archive
   * turn_index: Index of the archive turn to rehydrate
   * 
   * Returns:
   * RehydrateResult with restoration details
   */
  rehydrate(sessionId: string, turnIndex: number): Promise<Types.RehydrateResult>;

  /**
   * Remove a file from a session's prompt files.
   * 
   * Args:
   * session_id: Session to remove the prompt file from
   * file_path: Path of the file to remove
   * 
   * Returns:
   * Dict with success status, error message if any, and updated file list
   */
  removeSessionPromptFile(sessionId: string, filePath: string): Promise<Record<string, unknown>>;

  /**
   * Reopen a concluded session.
   * 
   * Clears the concluded flag and adds a reopen turn to the conversation.
   * 
   * Args:
   * session_id: ID of the session to reopen
   * reason: Optional reason for reopening
   * 
   * Returns:
   * ConcludeSessionResult (reused for reopen)
   */
  reopenSession(sessionId: string, reason?: string): Promise<Types.ConcludeSessionResult>;

  /**
   * Request the LLM to generate a proposal (fork, merge, or conclude).
   * 
   * Instead of directly executing a fork/merge/conclude, this method submits
   * a message instructing the LLM to use the appropriate proposal tool
   * (propose_fork, propose_merge). The user can then review and accept/reject
   * the proposal via the UI.
   * 
   * For conclude, the LLM generates a session summary before concluding.
   * 
   * Args:
   * session_id: ID of the session to generate a proposal for
   * proposal_type: Type of proposal ("fork", "merge", "conclude")
   * seed_prompt: User's seed text to guide the proposal. For fork, this
   * describes what the fork should accomplish. For merge,
   * this describes what was accomplished. For conclude,
   * this focuses the summary.
   * 
   * Returns:
   * RequestProposalResult with exchange_id for tracking the proposal
   */
  requestProposal(sessionId: string, proposalType: string, seedPrompt?: string): Promise<Types.RequestProposalResult>;

  /**
   * Respond to a fork proposal by accepting or rejecting it.
   * 
   * When accepting, optionally provide modified context_plan and initial_prompt.
   * The context_plan uses exchange ranges (like "0-2", "last") rather than
   * individual turn indices - this method handles the resolution.
   * 
   * Args:
   * session_id: ID of the session containing the proposal
   * proposal_id: ID of the proposal to respond to
   * accepted: True to accept, False to reject
   * context_plan: Modified context plan (list of {exchange_range, mode, reason})
   * If not provided, uses the original from the proposal
   * initial_prompt: Modified initial prompt (if not provided, uses original)
   * name: Fork name (if not provided, uses original from proposal)
   * description: Fork description (if not provided, uses original from proposal)
   * start_streaming: If True and accepted, start streaming after fork creation
   * backend_name: Backend/model to use for the fork. If not provided, inherits from parent.
   * 
   * Returns:
   * RespondToForkProposalResult with fork session info if accepted
   */
  respondToForkProposal(sessionId: string, proposalId: string, accepted: boolean, contextPlan?: Record<string, unknown>[] | null, initialPrompt?: string | null, name?: string | null, description?: string | null, startStreaming?: boolean, backendName?: string | null): Promise<Types.RespondToForkProposalResult>;

  /**
   * Respond to a merge proposal by accepting or rejecting it.
   * 
   * When accepting, optionally provide a modified summary.
   * 
   * Args:
   * session_id: ID of the session containing the proposal (the fork session)
   * proposal_id: ID of the proposal to respond to
   * accepted: True to accept, False to reject
   * summary: Modified merge summary (if not provided, uses original)
   * files_changed: Modified list of changed files
   * key_accomplishments: Modified list of accomplishments
   * reason: Modified reason for merge
   * 
   * Returns:
   * RespondToMergeProposalResult with merge info if accepted
   */
  respondToMergeProposal(sessionId: string, proposalId: string, accepted: boolean, summary?: string | null, filesChanged?: string[] | null, keyAccomplishments?: string[] | null, reason?: string | null): Promise<Types.RespondToMergeProposalResult>;

  /**
   * Set the default enabled tools in config.
   * 
   * This affects new sessions. Existing sessions keep their own enabled_tools.
   * 
   * Args:
   * tools: List of tool names to set as defaults
   * 
   * Returns:
   * True if successful
   */
  setDefaultEnabledTools(tools: string[]): Promise<boolean>;

  /**
   * Set the backend for a session.
   * 
   * The new backend will be used for the next streaming request.
   * Cannot change backend while streaming.
   * 
   * Args:
   * session_id: ID of the session to update
   * backend_name: Name of the backend to use
   * 
   * Returns:
   * True if successful, False if session not found or invalid backend
   */
  setSessionBackend(sessionId: string, backendName: string): Promise<boolean>;

  /**
   * Set the enabled tools for a session.
   * 
   * Args:
   * session_id: ID of the session to update
   * tools: List of tool names to enable
   * 
   * Returns:
   * True if successful, False if session not found
   */
  setSessionEnabledTools(sessionId: string, tools: string[]): Promise<boolean>;

  /**
   * Set the title for a session.
   * 
   * Args:
   * session_id: ID of the session to update
   * title: New title for the session
   * 
   * Returns:
   * True if successful, False if session not found
   */
  setSessionTitle(sessionId: string, title: string): Promise<boolean>;

  /**
   * Set the working directory for a session.
   * 
   * Args:
   * session_id: ID of the session to update
   * working_directory: New working directory path
   * 
   * Returns:
   * True if successful, False if session not found or path invalid
   */
  setSessionWorkingDirectory(sessionId: string, workingDirectory: string): Promise<boolean>;

  /**
   * Start archiving turns with LLM-generated summary.
   * 
   * This starts a background task to generate a summary of the turns being
   * archived. The actual archive is performed after the summary completes.
   * 
   * Args:
   * session_id: ID of the session to archive turns from
   * turn_indices: List of turn indices to archive (must be contiguous)
   * auto_complete: If True, automatically complete the archive after
   * summary generation. If False, client must call
   * complete_archive() manually.
   * 
   * Returns:
   * StartArchiveResult with helper_id for tracking progress
   */
  startArchive(sessionId: string, turnIndices: number[], autoComplete?: boolean): Promise<Types.StartArchiveResult>;

  /**
   * Start a session review using the specified backend.
   * 
   * This initiates an LLM call to analyze the session and generate a
   * structured review. The review runs asynchronously; use helper events
   * to track progress and complete_session_review() when done.
   * 
   * Args:
   * session_id: The session to review
   * backend_name: Which backend to use for generating the review
   * 
   * Returns:
   * StartSessionReviewResult with helper_id for tracking progress
   */
  startSessionReview(sessionId: string, backendName: string): Promise<Types.StartSessionReviewResult>;

  /**
   * Attach an existing session as a watcher of a target session.
   * 
   * This is the primary primitive for making any existing session, including
   * a fork, begin watching another session.
   */
  startWatchingSession(sessionId: string, targetSessionId: string): Promise<Types.CreateWatcherSessionResult>;

  /**
   * Stop a session from watching one or more targets.
   * 
   * Args:
   * session_id: ID of the session that is watching
   * target_session_id: ID of the target to stop watching (if None, stops all)
   * reason: Why watching stopped ("user", "session_closed", "session_archived")
   * 
   * Returns:
   * True if successfully stopped, False otherwise
   */
  stopWatchingSession(sessionId: string, targetSessionId?: string | null, reason?: string): Promise<boolean>;

  /**
   * Submit a markdown message to a session and start streaming the response.
   * 
   * Similar to submit_message but the user turn is stored and displayed as
   * a MarkdownBlock instead of TextBlock, allowing rich formatting (code blocks,
   * tables, etc.) in user-submitted content like code reviews.
   * 
   * Args:
   * session_id: ID of the session to submit to
   * content: The markdown content (user prompt)
   * queue: If True, queue the message instead of starting immediately.
   * allowed_tools: List of tool names to allow, or None for all tools
   * 
   * Returns:
   * SubmitMessageResult with IDs for tracking the stream
   * 
   * Raises:
   * ValueError: If session not found or already streaming (when queue=False)
   */
  submitMarkdownMessage(sessionId: string, content: string, queue?: boolean, allowedTools?: string[] | null): Promise<Types.SubmitMessageResult>;

  /**
   * Submit a message to a session and start streaming the response.
   * 
   * This is the primary way for frontends to interact with the LLM.
   * The message is added to the session and streaming begins immediately
   * (unless queue=True, in which case it waits for current stream to finish).
   * 
   * After calling this method, listen for streaming events via the observer pattern:
   * - on_turn_delta: Streaming text chunks
   * - on_tool_use_started: Tool execution beginning
   * - on_tool_result: Tool execution completed
   * - on_turn_finished: Exchange completed
   * 
   * Args:
   * session_id: ID of the session to submit to
   * content: The message content (user prompt)
   * messages: Context messages to include. If None, uses all session turns.
   * This allows frontends to curate which context is sent to the LLM.
   * queue: If True, queue the message instead of starting immediately.
   * If False and session is already streaming, returns error.
   * allowed_tools: List of tool names to allow, or None for all tools
   * 
   * Returns:
   * SubmitMessageResult with IDs for tracking the stream
   * 
   * Raises:
   * ValueError: If session not found or already streaming (when queue=False)
   */
  submitMessage(sessionId: string, content: string, messages?: unknown[] | null, queue?: boolean, allowedTools?: string[] | null): Promise<Types.SubmitMessageResult>;

  /**
   * Submit a message with image attachments to a session.
   * 
   * Similar to submit_message but includes images that Claude can see.
   * Images should be uploaded first via ImageService.upload_image().
   * 
   * Args:
   * session_id: ID of the session to submit to
   * content: The message content (user prompt)
   * images: List of image attachment dicts with keys:
   * - file_path: Path to uploaded image file
   * - media_type: MIME type (image/png, image/jpeg, etc.)
   * - filename: Optional display filename
   * - width: Optional image width
   * - height: Optional image height
   * queue: If True, queue the message instead of starting immediately.
   * allowed_tools: List of tool names to allow, or None for all tools
   * 
   * Returns:
   * SubmitMessageResult with IDs for tracking the stream
   * 
   * Raises:
   * ValueError: If session not found or already streaming (when queue=False)
   */
  submitMessageWithImages(sessionId: string, content: string, images: Record<string, unknown>[], queue?: boolean, allowedTools?: string[] | null): Promise<Types.SubmitMessageResult>;

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

  /**
   * Unload a domain plugin.
   * 
   * Args:
   * domain_id: ID of the domain to unload
   * session_id: Optional session to disassociate the domain from
   * 
   * Returns:
   * Dict with success status and error message if any
   */
  unloadDomain(domainId: string, sessionId?: string | null): Promise<Record<string, unknown>>;

  /**
   * Validate that a merge is possible for a fork session.
   * 
   * Use this to check if merge is valid before generating a summary.
   * Returns the parent session ID if valid.
   * 
   * Args:
   * fork_session_id: ID of the fork session to validate
   * 
   * Returns:
   * MergeSessionResult with success=True if valid, otherwise error
   */
  validateMerge(forkSessionId: string): Promise<Types.MergeSessionResult>;

}

export interface SessionManagerEvents {
  /**
   * Emitted when an archive operation completes successfully.
   */
  onArchiveCompleted(callback: (data: Types.CompleteArchiveResult) => void): Unsubscribe;

  /**
   * Emitted when an archive operation begins.
   */
  onArchiveStarted(callback: (data: Types.StartArchiveResult) => void): Unsubscribe;

  /**
   * Emitted when text content is streamed from a helper task.
   */
  onHelperDelta(callback: (data: Types.HelperDeltaEvent) => void): Unsubscribe;

  /**
   * Emitted when a helper task completes successfully.
   */
  onHelperDone(callback: (data: Types.HelperDoneEvent) => void): Unsubscribe;

  /**
   * Emitted when a helper task fails or is cancelled.
   */
  onHelperError(callback: (data: Types.HelperErrorEvent) => void): Unsubscribe;

  /**
   * Emitted when a helper task begins streaming.
   */
  onHelperStarted(callback: (data: Types.HelperStartedEvent) => void): Unsubscribe;

  /**
   * Emitted when a message is submitted and streaming begins.
   */
  onMessageSubmitted(callback: (data: Types.SubmitMessageResult) => void): Unsubscribe;

  /**
   * Emitted when a new session is created.
   */
  onSessionCreated(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when a session is deleted.
   */
  onSessionDeleted(callback: (data: Types.SessionEventData) => void): Unsubscribe;

  /**
   * Emitted when a session review completes successfully.
   */
  onSessionReviewCompleted(callback: (data: Types.CompleteSessionReviewResult) => void): Unsubscribe;

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
    const id = generateRequestId();
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

  async addSessionPromptFile(sessionId: string, filePath: string): Promise<Record<string, unknown>> {
    return this.call('addSessionPromptFile', { sessionId: sessionId, filePath: filePath });
  }

  async approveSessionReview(sessionId: string, summaryId: string, approvedTitle: string, editedMarkdown?: string | null): Promise<Types.ApproveSessionReviewResult> {
    return this.call('approveSessionReview', { sessionId: sessionId, summaryId: summaryId, approvedTitle: approvedTitle, editedMarkdown: editedMarkdown });
  }

  async awaitHelperResult(helperId: string, timeoutSeconds?: number): Promise<string> {
    return this.call('awaitHelperResult', { helperId: helperId, timeoutSeconds: timeoutSeconds });
  }

  async cancelStreaming(sessionId: string): Promise<boolean> {
    return this.call('cancelStreaming', { sessionId: sessionId });
  }

  async completeArchive(helperId: string, summary?: string | null): Promise<Types.CompleteArchiveResult> {
    return this.call('completeArchive', { helperId: helperId, summary: summary });
  }

  async completeDeriveAfterCompression(helperId: string, compressedSummary: string, startStreaming?: boolean): Promise<Types.DeriveSessionResult> {
    return this.call('completeDeriveAfterCompression', { helperId: helperId, compressedSummary: compressedSummary, startStreaming: startStreaming });
  }

  async completeForkAfterCompression(helperId: string, compressedSummary: string, startStreaming?: boolean): Promise<Types.ForkSessionResult> {
    return this.call('completeForkAfterCompression', { helperId: helperId, compressedSummary: compressedSummary, startStreaming: startStreaming });
  }

  async completeSessionReview(helperId: string, resultText: string): Promise<Types.CompleteSessionReviewResult> {
    return this.call('completeSessionReview', { helperId: helperId, resultText: resultText });
  }

  async concludeSession(sessionId: string, reason?: string): Promise<Types.ConcludeSessionResult> {
    return this.call('concludeSession', { sessionId: sessionId, reason: reason });
  }

  async createSession(workingDirectory?: string | null): Promise<Types.ManagedSessionInfo> {
    return this.call('createSession', { workingDirectory: workingDirectory });
  }

  async createWatcherSession(targetSessionId: string): Promise<Types.CreateWatcherSessionResult> {
    return this.call('createWatcherSession', { targetSessionId: targetSessionId });
  }

  async deleteSession(sessionId: string): Promise<boolean> {
    return this.call('deleteSession', { sessionId: sessionId });
  }

  async deriveSession(sourceSessionId: string, prompt?: string, contextModes?: Record<string, unknown>[] | null, allowedTools?: string[] | null, startStreaming?: boolean): Promise<Types.DeriveSessionResult> {
    return this.call('deriveSession', { sourceSessionId: sourceSessionId, prompt: prompt, contextModes: contextModes, allowedTools: allowedTools, startStreaming: startStreaming });
  }

  async findSwitchTarget(sessionId: string, name: string): Promise<Types.SwitchTargetResult> {
    return this.call('findSwitchTarget', { sessionId: sessionId, name: name });
  }

  async forkSession(parentSessionId: string, prompt: string, name?: string, background?: boolean, contextModes?: Record<string, unknown>[] | null, allowedTools?: string[] | null, startStreaming?: boolean, autoCompleteCompression?: boolean, backendName?: string): Promise<Types.ForkSessionResult> {
    return this.call('forkSession', { parentSessionId: parentSessionId, prompt: prompt, name: name, background: background, contextModes: contextModes, allowedTools: allowedTools, startStreaming: startStreaming, autoCompleteCompression: autoCompleteCompression, backendName: backendName });
  }

  async generateCommitMessage(gitRoot: string, stagedDiff: string): Promise<Types.GenerateCommitMessageResult> {
    return this.call('generateCommitMessage', { gitRoot: gitRoot, stagedDiff: stagedDiff });
  }

  async getActiveSessionId(): Promise<string | null> {
    return this.call('getActiveSessionId', {  });
  }

  async getAllStreamingInfo(): Promise<Types.StreamingInfo[]> {
    return this.call('getAllStreamingInfo', {  });
  }

  async getAvailableTools(): Promise<Record<string, unknown>> {
    return this.call('getAvailableTools', {  });
  }

  async getDefaultEnabledTools(): Promise<string[]> {
    return this.call('getDefaultEnabledTools', {  });
  }

  async getDomainInfo(): Promise<Record<string, unknown>> {
    return this.call('getDomainInfo', {  });
  }

  async getExchangeSummaries(sessionId: string, excludeCurrent?: boolean): Promise<Types.ExchangeSummary[]> {
    return this.call('getExchangeSummaries', { sessionId: sessionId, excludeCurrent: excludeCurrent });
  }

  async getPromptPreview(sessionId?: string | null, enabledTools?: string[] | null): Promise<Record<string, unknown>> {
    return this.call('getPromptPreview', { sessionId: sessionId, enabledTools: enabledTools });
  }

  async getRunnerContextPreview(sessionId: string, enabledTools?: string[] | null): Promise<Types.RunnerContextPreviewResult> {
    return this.call('getRunnerContextPreview', { sessionId: sessionId, enabledTools: enabledTools });
  }

  async getSession(sessionId: string): Promise<Types.ManagedSessionInfo | null> {
    return this.call('getSession', { sessionId: sessionId });
  }

  async getSessionBackend(sessionId: string): Promise<string | null> {
    return this.call('getSessionBackend', { sessionId: sessionId });
  }

  async getSessionEnabledTools(sessionId: string): Promise<string[]> {
    return this.call('getSessionEnabledTools', { sessionId: sessionId });
  }

  async getSessionPromptFiles(sessionId: string): Promise<Record<string, unknown>> {
    return this.call('getSessionPromptFiles', { sessionId: sessionId });
  }

  async getSessionReviews(sessionId: string): Promise<Record<string, unknown>[]> {
    return this.call('getSessionReviews', { sessionId: sessionId });
  }

  async getStreamingInfo(sessionId: string): Promise<Types.StreamingInfo | null> {
    return this.call('getStreamingInfo', { sessionId: sessionId });
  }

  async getStreamingSessions(): Promise<string[]> {
    return this.call('getStreamingSessions', {  });
  }

  async getSystemPromptInfo(sessionId?: string | null): Promise<Types.SystemPromptInfoResult> {
    return this.call('getSystemPromptInfo', { sessionId: sessionId });
  }

  async getToolSchemasPreview(sessionId?: string | null, enabledTools?: string[] | null): Promise<Record<string, unknown>> {
    return this.call('getToolSchemasPreview', { sessionId: sessionId, enabledTools: enabledTools });
  }

  async linkSessions(sourceSessionId: string, targetSessionId: string, summary?: string): Promise<Types.LinkSessionsResult> {
    return this.call('linkSessions', { sourceSessionId: sourceSessionId, targetSessionId: targetSessionId, summary: summary });
  }

  async listBackends(): Promise<string[]> {
    return this.call('listBackends', {  });
  }

  async listSessions(): Promise<Types.ManagedSessionInfo[]> {
    return this.call('listSessions', {  });
  }

  async loadDomain(domainId: string, sessionId?: string | null): Promise<Record<string, unknown>> {
    return this.call('loadDomain', { domainId: domainId, sessionId: sessionId });
  }

  async mergeSession(forkSessionId: string, mergeSummary: string, filesChanged?: string[] | null, keyAccomplishments?: string[] | null, reason?: string): Promise<Types.MergeSessionResult> {
    return this.call('mergeSession', { forkSessionId: forkSessionId, mergeSummary: mergeSummary, filesChanged: filesChanged, keyAccomplishments: keyAccomplishments, reason: reason });
  }

  async rehydrate(sessionId: string, turnIndex: number): Promise<Types.RehydrateResult> {
    return this.call('rehydrate', { sessionId: sessionId, turnIndex: turnIndex });
  }

  async removeSessionPromptFile(sessionId: string, filePath: string): Promise<Record<string, unknown>> {
    return this.call('removeSessionPromptFile', { sessionId: sessionId, filePath: filePath });
  }

  async reopenSession(sessionId: string, reason?: string): Promise<Types.ConcludeSessionResult> {
    return this.call('reopenSession', { sessionId: sessionId, reason: reason });
  }

  async requestProposal(sessionId: string, proposalType: string, seedPrompt?: string): Promise<Types.RequestProposalResult> {
    return this.call('requestProposal', { sessionId: sessionId, proposalType: proposalType, seedPrompt: seedPrompt });
  }

  async respondToForkProposal(sessionId: string, proposalId: string, accepted: boolean, contextPlan?: Record<string, unknown>[] | null, initialPrompt?: string | null, name?: string | null, description?: string | null, startStreaming?: boolean, backendName?: string | null): Promise<Types.RespondToForkProposalResult> {
    return this.call('respondToForkProposal', { sessionId: sessionId, proposalId: proposalId, accepted: accepted, contextPlan: contextPlan, initialPrompt: initialPrompt, name: name, description: description, startStreaming: startStreaming, backendName: backendName });
  }

  async respondToMergeProposal(sessionId: string, proposalId: string, accepted: boolean, summary?: string | null, filesChanged?: string[] | null, keyAccomplishments?: string[] | null, reason?: string | null): Promise<Types.RespondToMergeProposalResult> {
    return this.call('respondToMergeProposal', { sessionId: sessionId, proposalId: proposalId, accepted: accepted, summary: summary, filesChanged: filesChanged, keyAccomplishments: keyAccomplishments, reason: reason });
  }

  async setDefaultEnabledTools(tools: string[]): Promise<boolean> {
    return this.call('setDefaultEnabledTools', { tools: tools });
  }

  async setSessionBackend(sessionId: string, backendName: string): Promise<boolean> {
    return this.call('setSessionBackend', { sessionId: sessionId, backendName: backendName });
  }

  async setSessionEnabledTools(sessionId: string, tools: string[]): Promise<boolean> {
    return this.call('setSessionEnabledTools', { sessionId: sessionId, tools: tools });
  }

  async setSessionTitle(sessionId: string, title: string): Promise<boolean> {
    return this.call('setSessionTitle', { sessionId: sessionId, title: title });
  }

  async setSessionWorkingDirectory(sessionId: string, workingDirectory: string): Promise<boolean> {
    return this.call('setSessionWorkingDirectory', { sessionId: sessionId, workingDirectory: workingDirectory });
  }

  async startArchive(sessionId: string, turnIndices: number[], autoComplete?: boolean): Promise<Types.StartArchiveResult> {
    return this.call('startArchive', { sessionId: sessionId, turnIndices: turnIndices, autoComplete: autoComplete });
  }

  async startSessionReview(sessionId: string, backendName: string): Promise<Types.StartSessionReviewResult> {
    return this.call('startSessionReview', { sessionId: sessionId, backendName: backendName });
  }

  async startWatchingSession(sessionId: string, targetSessionId: string): Promise<Types.CreateWatcherSessionResult> {
    return this.call('startWatchingSession', { sessionId: sessionId, targetSessionId: targetSessionId });
  }

  async stopWatchingSession(sessionId: string, targetSessionId?: string | null, reason?: string): Promise<boolean> {
    return this.call('stopWatchingSession', { sessionId: sessionId, targetSessionId: targetSessionId, reason: reason });
  }

  async submitMarkdownMessage(sessionId: string, content: string, queue?: boolean, allowedTools?: string[] | null): Promise<Types.SubmitMessageResult> {
    return this.call('submitMarkdownMessage', { sessionId: sessionId, content: content, queue: queue, allowedTools: allowedTools });
  }

  async submitMessage(sessionId: string, content: string, messages?: unknown[] | null, queue?: boolean, allowedTools?: string[] | null): Promise<Types.SubmitMessageResult> {
    return this.call('submitMessage', { sessionId: sessionId, content: content, messages: messages, queue: queue, allowedTools: allowedTools });
  }

  async submitMessageWithImages(sessionId: string, content: string, images: Record<string, unknown>[], queue?: boolean, allowedTools?: string[] | null): Promise<Types.SubmitMessageResult> {
    return this.call('submitMessageWithImages', { sessionId: sessionId, content: content, images: images, queue: queue, allowedTools: allowedTools });
  }

  async switchSession(sessionId: string): Promise<boolean> {
    return this.call('switchSession', { sessionId: sessionId });
  }

  async unloadDomain(domainId: string, sessionId?: string | null): Promise<Record<string, unknown>> {
    return this.call('unloadDomain', { domainId: domainId, sessionId: sessionId });
  }

  async validateMerge(forkSessionId: string): Promise<Types.MergeSessionResult> {
    return this.call('validateMerge', { forkSessionId: forkSessionId });
  }

  onArchiveCompleted(callback: (data: Types.CompleteArchiveResult) => void): Unsubscribe {
    return this.subscribe('archiveCompleted', callback);
  }

  onArchiveStarted(callback: (data: Types.StartArchiveResult) => void): Unsubscribe {
    return this.subscribe('archiveStarted', callback);
  }

  onHelperDelta(callback: (data: Types.HelperDeltaEvent) => void): Unsubscribe {
    return this.subscribe('helperDelta', callback);
  }

  onHelperDone(callback: (data: Types.HelperDoneEvent) => void): Unsubscribe {
    return this.subscribe('helperDone', callback);
  }

  onHelperError(callback: (data: Types.HelperErrorEvent) => void): Unsubscribe {
    return this.subscribe('helperError', callback);
  }

  onHelperStarted(callback: (data: Types.HelperStartedEvent) => void): Unsubscribe {
    return this.subscribe('helperStarted', callback);
  }

  onMessageSubmitted(callback: (data: Types.SubmitMessageResult) => void): Unsubscribe {
    return this.subscribe('messageSubmitted', callback);
  }

  onSessionCreated(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('sessionCreated', callback);
  }

  onSessionDeleted(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('sessionDeleted', callback);
  }

  onSessionReviewCompleted(callback: (data: Types.CompleteSessionReviewResult) => void): Unsubscribe {
    return this.subscribe('sessionReviewCompleted', callback);
  }

  onSessionSwitched(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('sessionSwitched', callback);
  }

  onSessionUpdated(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('sessionUpdated', callback);
  }

  onStreamingStarted(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('streamingStarted', callback);
  }

  onStreamingStopped(callback: (data: Types.SessionEventData) => void): Unsubscribe {
    return this.subscribe('streamingStopped', callback);
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
   * Emitted when new text content streams from the LLM.
   * 
   * Subscribe to this event to render streaming text in real-time.
   * The `accumulated` field allows late-joining clients to catch up.
   */
  onContentDelta(callback: (data: Types.ContentDeltaEvent) => void): Unsubscribe;

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

  /**
   * Emitted when tool input JSON streams from the LLM.
   * 
   * Use this to show tool input as it's being generated.
   */
  onToolInputDelta(callback: (data: Types.ToolInputDeltaEvent) => void): Unsubscribe;

  /**
   * Emitted when a tool execution completes.
   * 
   * Contains the tool's output or error.
   */
  onToolResult(callback: (data: Types.ToolResultEvent) => void): Unsubscribe;

  /**
   * Emitted when tool input is complete and execution begins.
   * 
   * The full tool input is now available.
   */
  onToolUse(callback: (data: Types.ToolUseEvent) => void): Unsubscribe;

  /**
   * Emitted when the LLM begins a tool call.
   * 
   * The tool input may still be streaming at this point.
   */
  onToolUseStarted(callback: (data: Types.ToolUseStartedEvent) => void): Unsubscribe;

  /**
   * Emitted when a turn completes.
   * 
   * Use this to finalize UI rendering for the turn.
   */
  onTurnFinished(callback: (data: Types.TurnFinishedEvent) => void): Unsubscribe;

  /**
   * Emitted when a new turn begins (user, assistant, or tool).
   * 
   * Use this to create UI elements for the new turn.
   */
  onTurnStarted(callback: (data: Types.TurnStartedEvent) => void): Unsubscribe;

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
    const id = generateRequestId();
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

  onContentDelta(callback: (data: Types.ContentDeltaEvent) => void): Unsubscribe {
    return this.subscribe('contentDelta', callback);
  }

  onTaskCancelled(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('taskCancelled', callback);
  }

  onTaskCompleted(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('taskCompleted', callback);
  }

  onTaskError(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('taskError', callback);
  }

  onTaskStarted(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('taskStarted', callback);
  }

  onTaskUpdated(callback: (data: Types.TaskEventData) => void): Unsubscribe {
    return this.subscribe('taskUpdated', callback);
  }

  onToolInputDelta(callback: (data: Types.ToolInputDeltaEvent) => void): Unsubscribe {
    return this.subscribe('toolInputDelta', callback);
  }

  onToolResult(callback: (data: Types.ToolResultEvent) => void): Unsubscribe {
    return this.subscribe('toolResult', callback);
  }

  onToolUse(callback: (data: Types.ToolUseEvent) => void): Unsubscribe {
    return this.subscribe('toolUse', callback);
  }

  onToolUseStarted(callback: (data: Types.ToolUseStartedEvent) => void): Unsubscribe {
    return this.subscribe('toolUseStarted', callback);
  }

  onTurnFinished(callback: (data: Types.TurnFinishedEvent) => void): Unsubscribe {
    return this.subscribe('turnFinished', callback);
  }

  onTurnStarted(callback: (data: Types.TurnStartedEvent) => void): Unsubscribe {
    return this.subscribe('turnStarted', callback);
  }

}

/**
 * WebSocket-exposed service for session data streaming.
 * 
 * Provides subscription-based access to session content with efficient
 * delta streaming. Clients subscribe to sessions they want to observe
 * and receive real-time updates.
 * 
 * Key features:
 * - Per-session subscriptions (only receive events for subscribed sessions)
 * - Delta streaming for efficient bandwidth usage
 * - Snapshots for late-joining clients
 * - Turn lifecycle events (created, delta, finished)
 */
export interface SessionDataService {
  /**
   * Delete multiple turns from a session.
   * 
   * Args:
   * session_id: The session ID
   * turn_indices: List of turn indices to delete
   * 
   * Returns:
   * Number of turns actually deleted
   */
  deleteTurns(sessionId: string, turnIndices: number[]): Promise<number>;

  /**
   * Get all sessions with metadata.
   * 
   * Returns session list directly from LMDB storage, with pinning and
   * streaming state merged in.
   * 
   * Returns:
   * List of all sessions sorted by last_modified (most recent first)
   */
  getAllSessions(): Promise<Types.SessionInfo[]>;

  /**
   * Get all pinned session IDs.
   * 
   * Returns:
   * List of pinned session IDs
   */
  getPinnedSessions(): Promise<string[]>;

  /**
   * Get session metadata by ID.
   * 
   * Args:
   * session_id: The session ID to look up
   * 
   * Returns:
   * SessionInfo if found, None otherwise
   */
  getSession(sessionId: string): Promise<Types.SessionInfo | null>;

  /**
   * Get the full fork tree containing this session.
   * 
   * Finds the root ancestor and builds a tree of all related sessions,
   * including siblings, cousins, etc.
   * 
   * Args:
   * session_id: Any session ID in the tree
   * 
   * Returns:
   * ForkTreeNode representing the root, with nested children.
   * The target session is marked with is_current=True.
   * Returns None if session not found.
   */
  getSessionForkTree(sessionId: string): Promise<Types.ForkTreeNode | null>;

  /**
   * Get the parent chain for a session (ancestors from immediate parent to root).
   * 
   * This traverses the fork tree upward, returning all ancestor sessions
   * in order from immediate parent to the root session.
   * 
   * Args:
   * session_id: The session ID to get parents for
   * 
   * Returns:
   * List of SessionInfo for each parent, ordered from immediate parent to root.
   * Empty list if the session has no parent (is a root session).
   */
  getSessionParentChain(sessionId: string): Promise<Types.SessionInfo[]>;

  /**
   * Get a complete snapshot of the session's current state.
   * 
   * Use this when subscribing to get the initial state before
   * receiving incremental deltas.
   * 
   * Args:
   * session_id: The session to snapshot
   * 
   * Returns:
   * SessionSnapshot with full turn history, or None if session not found
   */
  getSessionSnapshot(sessionId: string): Promise<Types.SessionSnapshot | null>;

  /**
   * Get the number of clients subscribed to a session.
   * 
   * Args:
   * session_id: The session to check
   * 
   * Returns:
   * Number of subscribed clients
   */
  getSessionSubscriberCount(sessionId: string): Promise<number>;

  /**
   * Get watcher relationships for a session (lazy loading).
   * 
   * Returns both:
   * - watch_targets: sessions this session is watching
   * - watched_by: sessions that are watching this session
   * 
   * Args:
   * session_id: The session ID to get watcher info for
   * 
   * Returns:
   * SessionWatcherInfo with watch_targets and watched_by lists
   */
  getSessionWatcherInfo(sessionId: string): Promise<Types.SessionWatcherInfo>;

  /**
   * Get list of sessions a client is subscribed to.
   * 
   * Args:
   * client_id: The client's unique identifier
   * 
   * Returns:
   * List of session IDs the client is subscribed to
   */
  getSubscribedSessions(clientId: string): Promise<string[]>;

  /**
   * Check if a session is pinned.
   * 
   * Args:
   * session_id: The session to check
   * 
   * Returns:
   * True if session is pinned
   */
  isPinned(sessionId: string): Promise<boolean>;

  /**
   * Check if a session is currently streaming.
   * 
   * This is useful for refreshing client state after reconnection
   * or when the page becomes visible after being backgrounded.
   * 
   * Args:
   * session_id: The session to check
   * 
   * Returns:
   * True if the session has an active stream
   */
  isSessionStreaming(sessionId: string): Promise<boolean>;

  /**
   * Load a specific range of historical turns.
   * 
   * Used with lazy loading to request history on-demand, typically
   * when the user scrolls up to view older content.
   * 
   * Args:
   * session_id: The session to load from
   * client_id: The requesting client
   * start_order: First turn order to load (inclusive)
   * end_order: Last turn order to load (exclusive)
   * 
   * Returns:
   * SubscriptionResult indicating success/failure
   */
  loadHistoryRange(sessionId: string, clientId: string, startOrder: number, endOrder: number): Promise<Types.SubscriptionResult>;

  /**
   * Pin a session to appear at top of lists.
   * 
   * Args:
   * session_id: The session to pin
   * 
   * Returns:
   * True if newly pinned, False if already pinned or session doesn't exist
   */
  pinSession(sessionId: string): Promise<boolean>;

  /**
   * Reload a domain plugin, picking up code changes.
   * 
   * This is useful for development - when you modify domain code (like adding
   * @ws_expose decorators), call this to reload without restarting the server.
   * 
   * Args:
   * domain_id: The domain ID (e.g., "grocery")
   * 
   * Returns:
   * {"success": True, "methods": [...]} on success, {"error": "..."} on failure
   */
  reloadDomain(domainId: string): Promise<Record<string, unknown>>;

  /**
   * Request a domain to emit its current state.
   * 
   * This triggers the domain to emit a state sync event for the specified session.
   * The client should already be subscribed to receive domain events.
   * 
   * Gets raw state from the domain and wraps it in a state_sync event.
   * 
   * Args:
   * session_id: The session ID
   * domain_id: The domain ID (e.g., "chess")
   * 
   * Returns:
   * True if state was emitted, False if no state available
   */
  requestDomainState(sessionId: string, domainId: string): Promise<boolean>;

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
   * Add subscription layers for a session.
   * 
   * Layer-based subscriptions allow fine-grained control over which events
   * a client receives. Layers are additive - call multiple times to add more.
   * 
   * Layers:
   * - "header": Turn lifecycle events (created, completed, deleted) + stream status
   * - "body": Full turn content blocks on completion
   * - "delta": Live streaming events (text deltas, tool input deltas)
   * - "history": One-time historical turn loading (oldest-first, triggers historyChunk events)
   * - "history_reverse": One-time historical turn loading (newest-first for fast time-to-bottom)
   * - "history_lazy": Register for history but don't auto-load (use load_history_range on-demand)
   * 
   * Args:
   * session_id: The session to subscribe to
   * client_id: Unique identifier for the client
   * layers: List of layer names to add (e.g., ["header", "body"])
   * 
   * Returns:
   * SubscriptionResult with success/failure info
   */
  subscribeAdd(sessionId: string, clientId: string, layers: string[]): Promise<Types.SubscriptionResult>;

  /**
   * Remove subscription layers for a session.
   * 
   * Removes specific layers from a subscription. If all layers are removed,
   * the subscription is deleted entirely.
   * 
   * Args:
   * session_id: The session to modify
   * client_id: The client's identifier
   * layers: List of layer names to remove
   * 
   * Returns:
   * SubscriptionResult with success/failure info
   */
  subscribeRemove(sessionId: string, clientId: string, layers: string[]): Promise<Types.SubscriptionResult>;

  /**
   * Toggle pin state for a session.
   * 
   * Args:
   * session_id: The session to toggle
   * 
   * Returns:
   * True if now pinned, False if now unpinned
   */
  togglePin(sessionId: string): Promise<boolean>;

  /**
   * Unpin a session.
   * 
   * Args:
   * session_id: The session to unpin
   * 
   * Returns:
   * True if unpinned, False if wasn't pinned
   */
  unpinSession(sessionId: string): Promise<boolean>;

}

export interface SessionDataEvents {
  /**
   * Emitted when a domain plugin sends an event.
   * 
   * This bridges domain plugins (chess, etc.) to the frontend.
   * Contains domain_id, event_type, and event-specific data.
   */
  sessionDataDomainEvent(callback: (data: Types.SessionDomainEvent) => void): Unsubscribe;

  /**
   * Emitted when a chunk of historical turns is ready.
   * 
   * Sent incrementally during session subscription when the session
   * has historical turns. Clients should merge chunks by turn_id
   * and use the order field for sorting.
   */
  sessionDataHistoryChunk(callback: (data: Types.SessionHistoryChunkEvent) => void): Unsubscribe;

  /**
   * Emitted when all historical turns have been sent.
   * 
   * After receiving this event, clients can be confident they have
   * all historical data and can finalize the initial render.
   */
  sessionDataHistoryComplete(callback: (data: Types.SessionHistoryCompleteEvent) => void): Unsubscribe;

  /**
   * Emitted when the pinned sessions list changes.
   */
  sessionDataPinnedSessionsChanged(callback: (data: Types.PinnedSessionsChangedEvent) => void): Unsubscribe;

  /**
   * Emitted when a new session is created.
   * 
   * Clients should add the session to their session list.
   */
  sessionDataSessionAdded(callback: (data: Types.SessionAddedEvent) => void): Unsubscribe;

  /**
   * Emitted when a session's pin state changes.
   */
  sessionDataSessionPinned(callback: (data: Types.SessionPinnedEvent) => void): Unsubscribe;

  /**
   * Emitted when a session is deleted.
   * 
   * Clients should remove the session from their list.
   */
  sessionDataSessionRemoved(callback: (data: Types.SessionRemovedEvent) => void): Unsubscribe;

  /**
   * Emitted when session metadata changes.
   * 
   * Clients should update their session list display.
   */
  sessionDataSessionUpdated(callback: (data: Types.SessionUpdatedEvent) => void): Unsubscribe;

  /**
   * Emitted when streaming completes successfully.
   */
  sessionDataStreamDone(callback: (data: Types.SessionStreamDoneEvent) => void): Unsubscribe;

  /**
   * Emitted when streaming fails or is cancelled.
   */
  sessionDataStreamError(callback: (data: Types.SessionStreamErrorEvent) => void): Unsubscribe;

  /**
   * Emitted periodically during streaming with progress info.
   * 
   * Throttled to avoid flooding - provides status bar updates.
   */
  sessionDataStreamProgress(callback: (data: Types.SessionStreamProgressEvent) => void): Unsubscribe;

  /**
   * Emitted when streaming starts for a session.
   */
  sessionDataStreamStarted(callback: (data: Types.SessionStreamStartedEvent) => void): Unsubscribe;

  /**
   * Emitted while tool input JSON streams in.
   */
  sessionDataToolInputDelta(callback: (data: Types.SessionToolInputDeltaEvent) => void): Unsubscribe;

  /**
   * Emitted when a tool finishes execution.
   */
  sessionDataToolResult(callback: (data: Types.SessionToolResultEvent) => void): Unsubscribe;

  /**
   * Emitted while a running tool streams incremental output.
   */
  sessionDataToolResultDelta(callback: (data: Types.SessionToolResultDeltaEvent) => void): Unsubscribe;

  /**
   * Emitted when tool input is complete and execution begins.
   */
  sessionDataToolUse(callback: (data: Types.SessionToolUseEvent) => void): Unsubscribe;

  /**
   * Emitted when a tool begins execution.
   */
  sessionDataToolUseStarted(callback: (data: Types.SessionToolUseStartedEvent) => void): Unsubscribe;

  /**
   * Emitted when a new turn is created in a subscribed session.
   * 
   * Clients should create UI elements for the new turn.
   */
  sessionDataTurnCreated(callback: (data: Types.SessionTurnCreatedEvent) => void): Unsubscribe;

  /**
   * Emitted when content is added to a streaming turn.
   * 
   * Clients should append the delta to their accumulated content.
   * Use accumulated_length to verify sync.
   */
  sessionDataTurnDelta(callback: (data: Types.SessionTurnDeltaEvent) => void): Unsubscribe;

  /**
   * Emitted when a turn finishes streaming.
   * 
   * Clients should finalize the turn display and update token counts.
   */
  sessionDataTurnFinished(callback: (data: Types.SessionTurnFinishedEvent) => void): Unsubscribe;

  /**
   * Emitted when turns are deleted from a session (e.g., during archive).
   * 
   * Clients should remove the deleted turns from their local state.
   */
  sessionDataTurnsDeleted(callback: (data: Types.SessionTurnsDeletedEvent) => void): Unsubscribe;

  /**
   * Emitted when turn orders are recomputed (e.g., after archive/rehydrate).
   * 
   * Clients should update the order field for each turn in the mapping.
   * This fixes visual gaps in turn numbering after archive operations.
   */
  sessionDataTurnsReordered(callback: (data: Types.SessionTurnsReorderedEvent) => void): Unsubscribe;

}

export class SessionDataServiceClient implements SessionDataService {
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
    const id = generateRequestId();
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

  async deleteTurns(sessionId: string, turnIndices: number[]): Promise<number> {
    return this.call('deleteTurns', { sessionId: sessionId, turnIndices: turnIndices });
  }

  async getAllSessions(): Promise<Types.SessionInfo[]> {
    return this.call('getAllSessions', {  });
  }

  async getPinnedSessions(): Promise<string[]> {
    return this.call('getPinnedSessions', {  });
  }

  async getSession(sessionId: string): Promise<Types.SessionInfo | null> {
    return this.call('getSession', { sessionId: sessionId });
  }

  async getSessionForkTree(sessionId: string): Promise<Types.ForkTreeNode | null> {
    return this.call('getSessionForkTree', { sessionId: sessionId });
  }

  async getSessionParentChain(sessionId: string): Promise<Types.SessionInfo[]> {
    return this.call('getSessionParentChain', { sessionId: sessionId });
  }

  async getSessionSnapshot(sessionId: string): Promise<Types.SessionSnapshot | null> {
    return this.call('getSessionSnapshot', { sessionId: sessionId });
  }

  async getSessionSubscriberCount(sessionId: string): Promise<number> {
    return this.call('getSessionSubscriberCount', { sessionId: sessionId });
  }

  async getSessionWatcherInfo(sessionId: string): Promise<Types.SessionWatcherInfo> {
    return this.call('getSessionWatcherInfo', { sessionId: sessionId });
  }

  async getSubscribedSessions(clientId: string): Promise<string[]> {
    return this.call('getSubscribedSessions', { clientId: clientId });
  }

  async isPinned(sessionId: string): Promise<boolean> {
    return this.call('isPinned', { sessionId: sessionId });
  }

  async isSessionStreaming(sessionId: string): Promise<boolean> {
    return this.call('isSessionStreaming', { sessionId: sessionId });
  }

  async loadHistoryRange(sessionId: string, clientId: string, startOrder: number, endOrder: number): Promise<Types.SubscriptionResult> {
    return this.call('loadHistoryRange', { sessionId: sessionId, clientId: clientId, startOrder: startOrder, endOrder: endOrder });
  }

  async pinSession(sessionId: string): Promise<boolean> {
    return this.call('pinSession', { sessionId: sessionId });
  }

  async reloadDomain(domainId: string): Promise<Record<string, unknown>> {
    return this.call('reloadDomain', { domainId: domainId });
  }

  async requestDomainState(sessionId: string, domainId: string): Promise<boolean> {
    return this.call('requestDomainState', { sessionId: sessionId, domainId: domainId });
  }

  async setContextMode(sessionId: string, turnIdx: number, mode: string): Promise<null> {
    return this.call('setContextMode', { sessionId: sessionId, turnIdx: turnIdx, mode: mode });
  }

  async subscribeAdd(sessionId: string, clientId: string, layers: string[]): Promise<Types.SubscriptionResult> {
    return this.call('subscribeAdd', { sessionId: sessionId, clientId: clientId, layers: layers });
  }

  async subscribeRemove(sessionId: string, clientId: string, layers: string[]): Promise<Types.SubscriptionResult> {
    return this.call('subscribeRemove', { sessionId: sessionId, clientId: clientId, layers: layers });
  }

  async togglePin(sessionId: string): Promise<boolean> {
    return this.call('togglePin', { sessionId: sessionId });
  }

  async unpinSession(sessionId: string): Promise<boolean> {
    return this.call('unpinSession', { sessionId: sessionId });
  }

  sessionDataDomainEvent(callback: (data: Types.SessionDomainEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataDomainEvent', callback);
  }

  sessionDataHistoryChunk(callback: (data: Types.SessionHistoryChunkEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataHistoryChunk', callback);
  }

  sessionDataHistoryComplete(callback: (data: Types.SessionHistoryCompleteEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataHistoryComplete', callback);
  }

  sessionDataPinnedSessionsChanged(callback: (data: Types.PinnedSessionsChangedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataPinnedSessionsChanged', callback);
  }

  sessionDataSessionAdded(callback: (data: Types.SessionAddedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataSessionAdded', callback);
  }

  sessionDataSessionPinned(callback: (data: Types.SessionPinnedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataSessionPinned', callback);
  }

  sessionDataSessionRemoved(callback: (data: Types.SessionRemovedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataSessionRemoved', callback);
  }

  sessionDataSessionUpdated(callback: (data: Types.SessionUpdatedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataSessionUpdated', callback);
  }

  sessionDataStreamDone(callback: (data: Types.SessionStreamDoneEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataStreamDone', callback);
  }

  sessionDataStreamError(callback: (data: Types.SessionStreamErrorEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataStreamError', callback);
  }

  sessionDataStreamProgress(callback: (data: Types.SessionStreamProgressEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataStreamProgress', callback);
  }

  sessionDataStreamStarted(callback: (data: Types.SessionStreamStartedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataStreamStarted', callback);
  }

  sessionDataToolInputDelta(callback: (data: Types.SessionToolInputDeltaEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataToolInputDelta', callback);
  }

  sessionDataToolResult(callback: (data: Types.SessionToolResultEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataToolResult', callback);
  }

  sessionDataToolResultDelta(callback: (data: Types.SessionToolResultDeltaEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataToolResultDelta', callback);
  }

  sessionDataToolUse(callback: (data: Types.SessionToolUseEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataToolUse', callback);
  }

  sessionDataToolUseStarted(callback: (data: Types.SessionToolUseStartedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataToolUseStarted', callback);
  }

  sessionDataTurnCreated(callback: (data: Types.SessionTurnCreatedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataTurnCreated', callback);
  }

  sessionDataTurnDelta(callback: (data: Types.SessionTurnDeltaEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataTurnDelta', callback);
  }

  sessionDataTurnFinished(callback: (data: Types.SessionTurnFinishedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataTurnFinished', callback);
  }

  sessionDataTurnsDeleted(callback: (data: Types.SessionTurnsDeletedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataTurnsDeleted', callback);
  }

  sessionDataTurnsReordered(callback: (data: Types.SessionTurnsReorderedEvent) => void): Unsubscribe {
    return this.subscribe('sessionDataTurnsReordered', callback);
  }

}

/**
 * WebSocket-exposed service for image management.
 * 
 * Handles image upload, storage, retrieval, and cleanup.
 * Images are stored on disk with unique filenames based on content hash.
 */
export interface ImageService {
  /**
   * Clean up images older than the retention period.
   * 
   * Args:
   * max_age_hours: Max age in hours (defaults to service retention setting)
   * 
   * Returns:
   * Number of images deleted
   */
  cleanupOldImages(maxAgeHours?: number | null): Promise<number>;

  /**
   * Delete an uploaded image.
   * 
   * Args:
   * file_path: Path to the image file
   * 
   * Returns:
   * True if deleted, False if not found
   */
  deleteImage(filePath: string): Promise<boolean>;

  /**
   * Get information about a stored image.
   * 
   * Args:
   * file_path: Path to the image file
   * 
   * Returns:
   * ImageInfo if found, None otherwise
   */
  getImageInfo(filePath: string): Promise<Types.ImageInfo | null>;

  /**
   * Get all image paths uploaded by a session.
   * 
   * Args:
   * session_id: The session ID
   * 
   * Returns:
   * List of file paths
   */
  getSessionImages(sessionId: string): Promise<string[]>;

  /**
   * Get the upload directory path.
   * 
   * Returns:
   * Absolute path to upload directory
   */
  getUploadDir(): Promise<string>;

  /**
   * Upload an image from base64 data.
   * 
   * Args:
   * data_base64: Base64-encoded image data
   * media_type: MIME type (image/png, image/jpeg, etc.)
   * session_id: Optional session ID to associate with this image
   * original_filename: Optional original filename
   * 
   * Returns:
   * ImageUploadResult with file path and metadata
   * 
   * Raises:
   * ValueError: If media type is not supported or data is invalid
   */
  uploadImage(dataBase64: string, mediaType: string, sessionId?: string | null, originalFilename?: string | null): Promise<Types.ImageUploadResult>;

}

export interface ImageEvents {
  /**
   * Emitted when cleanup completes.
   */
  onCleanupCompleted(callback: (data: Types.ImageEventData) => void): Unsubscribe;

  /**
   * Emitted when an image is deleted.
   */
  onImageDeleted(callback: (data: Types.ImageEventData) => void): Unsubscribe;

  /**
   * Emitted when an image is uploaded.
   */
  onImageUploaded(callback: (data: Types.ImageEventData) => void): Unsubscribe;

}

export class ImageServiceClient implements ImageService {
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
    const id = generateRequestId();
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

  async cleanupOldImages(maxAgeHours?: number | null): Promise<number> {
    return this.call('cleanupOldImages', { maxAgeHours: maxAgeHours });
  }

  async deleteImage(filePath: string): Promise<boolean> {
    return this.call('deleteImage', { filePath: filePath });
  }

  async getImageInfo(filePath: string): Promise<Types.ImageInfo | null> {
    return this.call('getImageInfo', { filePath: filePath });
  }

  async getSessionImages(sessionId: string): Promise<string[]> {
    return this.call('getSessionImages', { sessionId: sessionId });
  }

  async getUploadDir(): Promise<string> {
    return this.call('getUploadDir', {  });
  }

  async uploadImage(dataBase64: string, mediaType: string, sessionId?: string | null, originalFilename?: string | null): Promise<Types.ImageUploadResult> {
    return this.call('uploadImage', { dataBase64: dataBase64, mediaType: mediaType, sessionId: sessionId, originalFilename: originalFilename });
  }

  onCleanupCompleted(callback: (data: Types.ImageEventData) => void): Unsubscribe {
    return this.subscribe('cleanupCompleted', callback);
  }

  onImageDeleted(callback: (data: Types.ImageEventData) => void): Unsubscribe {
    return this.subscribe('imageDeleted', callback);
  }

  onImageUploaded(callback: (data: Types.ImageEventData) => void): Unsubscribe {
    return this.subscribe('imageUploaded', callback);
  }

}

/**
 * WebSocket-exposed service for file browsing with git status.
 * 
 * Provides directory listing with git status integration and session CWD management.
 */
export interface FileStateService {
  /**
   * Clear the CWD for a session (e.g., when session is deleted).
   * 
   * Args:
   * session_id: The session ID to clear
   */
  clearSessionCwd(sessionId: string): Promise<null>;

  /**
   * Generate a simple commit message based on staged changes.
   * 
   * This creates a basic summary of the staged changes (just lists filenames).
   * For AI-powered commit messages, use SessionManagerService.generateCommitMessage.
   * 
   * Args:
   * git_root: The git repository root directory
   * 
   * Returns:
   * A suggested commit message
   */
  generateSimpleCommitMessage(gitRoot: string): Promise<string>;

  /**
   * Get all session CWDs.
   * 
   * Returns:
   * List of session CWD mappings
   */
  getAllCwds(): Promise<Types.SessionCwd[]>;

  /**
   * Get the current working directory for a session.
   * 
   * Args:
   * session_id: The session ID
   * 
   * Returns:
   * The current working directory, or server's cwd if not set
   */
  getCwd(sessionId: string): Promise<string>;

  /**
   * Get git diff for a directory.
   * 
   * Returns the unstaged (or staged) changes in a git repository.
   * Parses the unified diff format into structured data.
   * 
   * Args:
   * path: Path to a directory inside a git repository
   * staged: If True, show staged changes; if False, show unstaged changes
   * 
   * Returns:
   * GitDiffResult with parsed diff information
   * 
   * Raises:
   * ValueError: If path is not in a git repository
   */
  getGitDiff(path: string, staged?: boolean): Promise<Types.GitDiffResult>;

  /**
   * Get the user's home directory.
   * 
   * Returns:
   * The home directory path
   */
  getHomeDirectory(): Promise<string>;

  /**
   * Get the parent directory of a path.
   * 
   * Args:
   * path: The path to get parent of
   * 
   * Returns:
   * The parent directory path
   */
  getParentDirectory(path: string): Promise<string>;

  /**
   * Get the diff of staged changes.
   * 
   * Args:
   * git_root: The git repository root directory
   * 
   * Returns:
   * GitDiffResult with staged changes
   */
  getStagedDiff(gitRoot: string): Promise<Types.GitDiffResult>;

  /**
   * Get the full working tree status including staged, unstaged, and untracked files.
   * 
   * This provides a complete view of the git state, suitable for displaying
   * a staging interface where users can stage/unstage individual files.
   * 
   * Args:
   * path: Path to a directory inside a git repository
   * 
   * Returns:
   * WorkingTreeStatus with staged, unstaged, and untracked files
   * 
   * Raises:
   * ValueError: If path is not in a git repository
   */
  getWorkingTreeStatus(path: string): Promise<Types.WorkingTreeStatus>;

  /**
   * Create a git commit with the staged changes using git2.
   * 
   * Args:
   * git_root: The git repository root directory
   * message: The commit message
   * 
   * Returns:
   * Operation result with success/failure status and commit hash
   */
  gitCommit(gitRoot: string, message: string): Promise<Types.FileOperationResult>;

  /**
   * Check if a path is a directory.
   * 
   * Args:
   * path: The path to check
   * 
   * Returns:
   * True if the path is a directory
   */
  isDirectory(path: string): Promise<boolean>;

  /**
   * List a directory with git status information.
   * 
   * Hidden files (starting with '.') are excluded from the listing.
   * Entries are sorted with directories first, then alphabetically by name.
   * 
   * Args:
   * path: Absolute path to the directory to list
   * 
   * Returns:
   * DirectoryListing with entries enriched with git status
   * 
   * Raises:
   * ValueError: If path doesn't exist or isn't a directory
   */
  listDirectory(path: string): Promise<Types.DirectoryListing>;

  /**
   * List a directory including hidden files.
   * 
   * Same as list_directory but includes files starting with '.'.
   * 
   * Args:
   * path: Absolute path to the directory to list
   * 
   * Returns:
   * DirectoryListing with all entries (including hidden)
   */
  listDirectoryWithHidden(path: string): Promise<Types.DirectoryListing>;

  /**
   * Check if a path exists.
   * 
   * Args:
   * path: The path to check
   * 
   * Returns:
   * True if the path exists
   */
  pathExists(path: string): Promise<boolean>;

  /**
   * Read a file's content.
   * 
   * Args:
   * path: Absolute path to the file
   * 
   * Returns:
   * The file content as a string
   * 
   * Raises:
   * ValueError: If path doesn't exist or is a directory
   */
  readFile(path: string): Promise<string>;

  /**
   * Resolve a relative path against a base directory.
   * 
   * Args:
   * base: The base directory
   * relative: The relative path (can include .. and .)
   * 
   * Returns:
   * The resolved absolute path
   */
  resolvePath(base: string, relative: string): Promise<string>;

  /**
   * Set the current working directory for a session.
   * 
   * Args:
   * session_id: The session ID
   * cwd: The new working directory (must exist)
   * 
   * Returns:
   * Operation result with success/failure status
   */
  setCwd(sessionId: string, cwd: string): Promise<Types.FileOperationResult>;

  /**
   * Stage all changes (tracked and untracked files) using git2.
   * 
   * Args:
   * git_root: The git repository root directory
   * 
   * Returns:
   * Operation result with success/failure status
   */
  stageAllChanges(gitRoot: string): Promise<Types.FileOperationResult>;

  /**
   * Stage files for commit using git2 (libgit2).
   * 
   * Args:
   * git_root: The git repository root directory
   * paths: List of file paths (relative to git root) to stage
   * 
   * Returns:
   * Operation result with success/failure status
   */
  stageFiles(gitRoot: string, paths: string[]): Promise<Types.FileOperationResult>;

  /**
   * Unstage files (remove from staging area) using git2.
   * 
   * Args:
   * git_root: The git repository root directory
   * paths: List of file paths (relative to git root) to unstage
   * 
   * Returns:
   * Operation result with success/failure status
   */
  unstageFiles(gitRoot: string, paths: string[]): Promise<Types.FileOperationResult>;

  /**
   * Write content to a file.
   * 
   * Creates the file if it doesn't exist. Creates parent directories if needed.
   * Uses atomic write (write to temp file, then rename) for safety.
   * 
   * Args:
   * path: Absolute path to the file
   * content: The content to write
   * 
   * Returns:
   * FileOperationResult with success/failure status
   */
  writeFile(path: string, content: string): Promise<Types.FileOperationResult>;

}

export interface FileStateEvents {
  /**
   * Emitted when a session's CWD changes.
   */
  onCwdChanged(callback: (data: Types.CwdChangedData) => void): Unsubscribe;

  /**
   * Emitted when a watched directory's contents change.
   * 
   * Note: Directory watching is not yet implemented.
   */
  onDirectoryChanged(callback: (data: Types.DirectoryListing) => void): Unsubscribe;

}

export class FileStateServiceClient implements FileStateService {
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
    const id = generateRequestId();
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

  async clearSessionCwd(sessionId: string): Promise<null> {
    return this.call('clearSessionCwd', { sessionId: sessionId });
  }

  async generateSimpleCommitMessage(gitRoot: string): Promise<string> {
    return this.call('generateSimpleCommitMessage', { gitRoot: gitRoot });
  }

  async getAllCwds(): Promise<Types.SessionCwd[]> {
    return this.call('getAllCwds', {  });
  }

  async getCwd(sessionId: string): Promise<string> {
    return this.call('getCwd', { sessionId: sessionId });
  }

  async getGitDiff(path: string, staged?: boolean): Promise<Types.GitDiffResult> {
    return this.call('getGitDiff', { path: path, staged: staged });
  }

  async getHomeDirectory(): Promise<string> {
    return this.call('getHomeDirectory', {  });
  }

  async getParentDirectory(path: string): Promise<string> {
    return this.call('getParentDirectory', { path: path });
  }

  async getStagedDiff(gitRoot: string): Promise<Types.GitDiffResult> {
    return this.call('getStagedDiff', { gitRoot: gitRoot });
  }

  async getWorkingTreeStatus(path: string): Promise<Types.WorkingTreeStatus> {
    return this.call('getWorkingTreeStatus', { path: path });
  }

  async gitCommit(gitRoot: string, message: string): Promise<Types.FileOperationResult> {
    return this.call('gitCommit', { gitRoot: gitRoot, message: message });
  }

  async isDirectory(path: string): Promise<boolean> {
    return this.call('isDirectory', { path: path });
  }

  async listDirectory(path: string): Promise<Types.DirectoryListing> {
    return this.call('listDirectory', { path: path });
  }

  async listDirectoryWithHidden(path: string): Promise<Types.DirectoryListing> {
    return this.call('listDirectoryWithHidden', { path: path });
  }

  async pathExists(path: string): Promise<boolean> {
    return this.call('pathExists', { path: path });
  }

  async readFile(path: string): Promise<string> {
    return this.call('readFile', { path: path });
  }

  async resolvePath(base: string, relative: string): Promise<string> {
    return this.call('resolvePath', { base: base, relative: relative });
  }

  async setCwd(sessionId: string, cwd: string): Promise<Types.FileOperationResult> {
    return this.call('setCwd', { sessionId: sessionId, cwd: cwd });
  }

  async stageAllChanges(gitRoot: string): Promise<Types.FileOperationResult> {
    return this.call('stageAllChanges', { gitRoot: gitRoot });
  }

  async stageFiles(gitRoot: string, paths: string[]): Promise<Types.FileOperationResult> {
    return this.call('stageFiles', { gitRoot: gitRoot, paths: paths });
  }

  async unstageFiles(gitRoot: string, paths: string[]): Promise<Types.FileOperationResult> {
    return this.call('unstageFiles', { gitRoot: gitRoot, paths: paths });
  }

  async writeFile(path: string, content: string): Promise<Types.FileOperationResult> {
    return this.call('writeFile', { path: path, content: content });
  }

  onCwdChanged(callback: (data: Types.CwdChangedData) => void): Unsubscribe {
    return this.subscribe('cwdChanged', callback);
  }

  onDirectoryChanged(callback: (data: Types.DirectoryListing) => void): Unsubscribe {
    return this.subscribe('directoryChanged', callback);
  }

}

/**
 * WebSocket-exposed service for debug logging.
 * 
 * Provides a way for web clients to send log entries to the shared
 * debug log, making them visible in the TUI's debug pane.
 */
export interface DebugLogService {
  /**
   * Clear log entries from a buffer.
   * 
   * Args:
   * category: Category to clear, or None to clear all
   * 
   * Returns:
   * LogResult with success status
   */
  clearBuffer(category?: string | null): Promise<Types.LogResult>;

  /**
   * Clear category filter to log all categories.
   * 
   * Returns:
   * LogResult with success status
   */
  clearCategories(): Promise<Types.LogResult>;

  /**
   * Convenience method to log a debug message.
   */
  debug(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult>;

  /**
   * Disable logging for a specific category.
   * 
   * Args:
   * category: Category to disable
   * 
   * Returns:
   * LogResult with success status
   */
  disableCategory(category: string): Promise<Types.LogResult>;

  /**
   * Enable logging for a specific category.
   * 
   * When any categories are enabled, only those categories will be logged.
   * Useful for targeted debugging.
   * 
   * Categories for API debugging:
   * - 'api': API requests, responses, chunks
   * - 'tool': Tool execution
   * - 'json': JSON parsing errors
   * - 'process': Process lifecycle
   * 
   * Args:
   * category: Category to enable
   * 
   * Returns:
   * LogResult with success status
   */
  enableCategory(category: string): Promise<Types.LogResult>;

  /**
   * Convenience method to log an error.
   */
  error(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult>;

  /**
   * Get all valid category names.
   * 
   * Returns:
   * List of all category names that have dedicated buffers
   */
  getAllCategories(): Promise<string[]>;

  /**
   * Get statistics for all category buffers.
   * 
   * Returns:
   * List of BufferStats for each category
   */
  getBufferStats(): Promise<Types.BufferStats[]>;

  /**
   * Get the list of currently enabled categories.
   * 
   * Returns:
   * List of enabled category names, or empty list if all are enabled
   */
  getCategories(): Promise<string[]>;

  /**
   * Get the current minimum log level.
   * 
   * Returns:
   * Current log level as string (e.g., 'debug', 'trace')
   */
  getLevel(): Promise<string>;

  /**
   * Get server identity (git state, metadata).
   * 
   * Returns the server's git commit, branch, dirty status, and
   * diff hash (fingerprint of local changes). Useful for debugging
   * to confirm what code version is running.
   * 
   * Returns:
   * ServerIdentityInfo or None if not captured
   */
  getServerIdentity(): Promise<Types.ServerIdentityInfo | null>;

  /**
   * Convenience method to log an info message.
   */
  info(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult>;

  /**
   * Check if debug logging is enabled.
   * 
   * Returns:
   * True if debug logging is enabled
   */
  isEnabled(): Promise<boolean>;

  /**
   * Log a message from a web client.
   * 
   * The log entry will appear in the TUI's debug pane with the specified
   * level, message, and category. Category defaults to "web" for web
   * client logs.
   * 
   * Args:
   * entry: The log entry to add
   * 
   * Returns:
   * LogResult with success status and sequence number
   */
  log(entry: Types.LogEntryInput): Promise<Types.LogResult>;

  /**
   * Log multiple messages at once.
   * 
   * Useful for flushing buffered logs from the web client.
   * 
   * Args:
   * entries: List of log entries to add
   * 
   * Returns:
   * LogResult with success status and last sequence number
   */
  logBatch(entries: Types.LogEntryInput[]): Promise<Types.LogResult>;

  /**
   * Query log entries from a specific category's buffer.
   * 
   * This is the primary query method for v2. Use this to efficiently
   * query entries from a single category's ring buffer.
   * 
   * Args:
   * category: Category to query (e.g., 'api', 'runner')
   * limit: Max entries to return (newest first)
   * level: Filter by log level (optional)
   * session_id: Filter by session (optional)
   * run_id: Filter by run (optional)
   * 
   * Returns:
   * QueryResult with matching entries and total buffer count
   */
  query(category: string, limit?: number, level?: string | null, sessionId?: string | null, runId?: string | null): Promise<Types.QueryResult>;

  /**
   * Set the buffer size for a category.
   * 
   * Args:
   * category: Category name
   * size: New max size (must be > 0)
   * 
   * Returns:
   * LogResult with success status
   */
  setBufferSize(category: string, size: number): Promise<Types.LogResult>;

  /**
   * Set the list of enabled categories.
   * 
   * Pass an empty list to log all categories (default behavior).
   * 
   * Args:
   * categories: List of category names to enable
   * 
   * Returns:
   * LogResult with success status
   */
  setCategories(categories: string[]): Promise<Types.LogResult>;

  /**
   * Enable or disable debug logging globally.
   * 
   * When disabled, no entries are added to buffers or files.
   * This is the main on/off switch for all debug logging.
   * 
   * Args:
   * enabled: True to enable, False to disable
   * 
   * Returns:
   * LogResult with success status
   */
  setEnabled(enabled: boolean): Promise<Types.LogResult>;

  /**
   * Set the minimum log level for the debug log.
   * 
   * This controls what gets logged on the server side. Use 'trace' for
   * maximum verbosity when debugging API issues.
   * 
   * Args:
   * level: One of 'error', 'warning', 'info', 'perf', 'debug', 'trace'
   * 
   * Returns:
   * LogResult with success status
   */
  setLevel(level: string): Promise<Types.LogResult>;

  /**
   * Convenience method to log a warning.
   */
  warning(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult>;

}

export class DebugLogServiceClient implements DebugLogService {
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
    const id = generateRequestId();
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

  async clearBuffer(category?: string | null): Promise<Types.LogResult> {
    return this.call('clearBuffer', { category: category });
  }

  async clearCategories(): Promise<Types.LogResult> {
    return this.call('clearCategories', {  });
  }

  async debug(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult> {
    return this.call('debug', { message: message, category: category, sessionId: sessionId, details: details });
  }

  async disableCategory(category: string): Promise<Types.LogResult> {
    return this.call('disableCategory', { category: category });
  }

  async enableCategory(category: string): Promise<Types.LogResult> {
    return this.call('enableCategory', { category: category });
  }

  async error(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult> {
    return this.call('error', { message: message, category: category, sessionId: sessionId, details: details });
  }

  async getAllCategories(): Promise<string[]> {
    return this.call('getAllCategories', {  });
  }

  async getBufferStats(): Promise<Types.BufferStats[]> {
    return this.call('getBufferStats', {  });
  }

  async getCategories(): Promise<string[]> {
    return this.call('getCategories', {  });
  }

  async getLevel(): Promise<string> {
    return this.call('getLevel', {  });
  }

  async getServerIdentity(): Promise<Types.ServerIdentityInfo | null> {
    return this.call('getServerIdentity', {  });
  }

  async info(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult> {
    return this.call('info', { message: message, category: category, sessionId: sessionId, details: details });
  }

  async isEnabled(): Promise<boolean> {
    return this.call('isEnabled', {  });
  }

  async log(entry: Types.LogEntryInput): Promise<Types.LogResult> {
    return this.call('log', { entry: entry });
  }

  async logBatch(entries: Types.LogEntryInput[]): Promise<Types.LogResult> {
    return this.call('logBatch', { entries: entries });
  }

  async query(category: string, limit?: number, level?: string | null, sessionId?: string | null, runId?: string | null): Promise<Types.QueryResult> {
    return this.call('query', { category: category, limit: limit, level: level, sessionId: sessionId, runId: runId });
  }

  async setBufferSize(category: string, size: number): Promise<Types.LogResult> {
    return this.call('setBufferSize', { category: category, size: size });
  }

  async setCategories(categories: string[]): Promise<Types.LogResult> {
    return this.call('setCategories', { categories: categories });
  }

  async setEnabled(enabled: boolean): Promise<Types.LogResult> {
    return this.call('setEnabled', { enabled: enabled });
  }

  async setLevel(level: string): Promise<Types.LogResult> {
    return this.call('setLevel', { level: level });
  }

  async warning(message: string, category?: string, sessionId?: string, details?: Record<string, unknown> | null): Promise<Types.LogResult> {
    return this.call('warning', { message: message, category: category, sessionId: sessionId, details: details });
  }

}

/**
 * WebSocket-exposed service for sound file management.
 * 
 * Handles listing available sounds, retrieving sound data for browser playback,
 * and uploading custom sounds.
 */
export interface SoundService {
  /**
   * Delete a sound file.
   * 
   * Args:
   * filename: Name of the sound file to delete
   * 
   * Returns:
   * True if deleted, False if not found
   */
  deleteSound(filename: string): Promise<boolean>;

  /**
   * Get sound file data for browser playback.
   * 
   * Args:
   * filename: Name of the sound file
   * 
   * Returns:
   * SoundData with base64-encoded audio, or None if not found
   */
  getSoundData(filename: string): Promise<Types.SoundData | null>;

  /**
   * Get the sounds directory path.
   * 
   * Returns:
   * Absolute path to sounds directory
   */
  getSoundsDir(): Promise<string>;

  /**
   * List all available sound files.
   * 
   * Returns:
   * List of SoundInfo objects for each sound file.
   */
  listSounds(): Promise<Types.SoundInfo[]>;

  /**
   * Upload a custom sound file.
   * 
   * Args:
   * data_base64: Base64-encoded audio data
   * filename: Desired filename
   * media_type: MIME type (audio/ogg, audio/mpeg, etc.)
   * 
   * Returns:
   * SoundUploadResult with success status
   */
  uploadSound(dataBase64: string, filename: string, mediaType: string): Promise<Types.SoundUploadResult>;

}

export interface SoundEvents {
  /**
   * Emitted when a sound is deleted.
   */
  onSoundDeleted(callback: (data: Types.SoundEventData) => void): Unsubscribe;

  /**
   * Emitted when a sound is uploaded.
   */
  onSoundUploaded(callback: (data: Types.SoundEventData) => void): Unsubscribe;

}

export class SoundServiceClient implements SoundService {
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
    const id = generateRequestId();
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

  async deleteSound(filename: string): Promise<boolean> {
    return this.call('deleteSound', { filename: filename });
  }

  async getSoundData(filename: string): Promise<Types.SoundData | null> {
    return this.call('getSoundData', { filename: filename });
  }

  async getSoundsDir(): Promise<string> {
    return this.call('getSoundsDir', {  });
  }

  async listSounds(): Promise<Types.SoundInfo[]> {
    return this.call('listSounds', {  });
  }

  async uploadSound(dataBase64: string, filename: string, mediaType: string): Promise<Types.SoundUploadResult> {
    return this.call('uploadSound', { dataBase64: dataBase64, filename: filename, mediaType: mediaType });
  }

  onSoundDeleted(callback: (data: Types.SoundEventData) => void): Unsubscribe {
    return this.subscribe('soundDeleted', callback);
  }

  onSoundUploaded(callback: (data: Types.SoundEventData) => void): Unsubscribe {
    return this.subscribe('soundUploaded', callback);
  }

}

/**
 * WebSocket-exposed service for supervisor state management.
 * 
 * Provides:
 * - Host configuration and status queries
 * - Process listing and management
 * - Real-time status updates via events
 */
export interface SupervisorStateService {
  /**
   * Add a new host to the configuration.
   * 
   * Args:
   * request: Host configuration
   * 
   * Returns:
   * Success/failure result
   */
  addHost(request: Types.HostUpdateRequest | Record<string, unknown>): Promise<Types.ConfigUpdateResult>;

  /**
   * Check connectivity status of a host.
   * 
   * For SSH hosts, performs a quick connection test.
   * For local, always returns ready.
   * 
   * Args:
   * host_name: Name of the host to check
   * 
   * Returns:
   * Status result with connectivity info
   */
  checkHostStatus(hostName: string): Promise<Types.HostStatusResult>;

  /**
   * Get historical output from a process.
   * 
   * Supports pagination - entries are returned in chronological order.
   * Use offset to fetch older entries.
   * 
   * Args:
   * process_id: The process ID to get output from
   * limit: Maximum entries to return (default 100, max 500)
   * offset: Number of entries to skip from the end (for pagination)
   * source: Filter to specific source ("stdout", "stderr", "stdin", "system")
   * 
   * Returns:
   * Batch of log entries with pagination info
   */
  getProcessOutput(processId: string, limit?: number, offset?: number, source?: string | null): Promise<Types.ProcessOutputBatch>;

  /**
   * Get the status of backend and UI servers.
   * 
   * Returns:
   * Dict with backend_a, backend_b, and ui server status
   */
  getServerStatus(): Promise<Record<string, unknown>>;

  /**
   * Get the complete supervisor state.
   * 
   * Returns all hosts, processes, and backend mappings.
   */
  getState(): Promise<Types.SupervisorState>;

  /**
   * Query hosts by tags and/or type.
   * 
   * Args:
   * tags: Filter to hosts with ALL specified tags
   * host_type: Filter to hosts of this type ("local" or "ssh")
   * 
   * Returns:
   * List of matching hosts
   */
  listHosts(tags?: string[] | null, hostType?: string | null): Promise<Types.HostQueryResult>;

  /**
   * List supervised processes.
   * 
   * Args:
   * session_id: Filter to processes for this session
   * host: Filter to processes on this host
   * process_type: Filter by type: "general", "lsp", or None for all
   * 
   * Returns:
   * List of processes with summary
   */
  listProcesses(sessionId?: string | null, host?: string | null, processType?: string | null): Promise<Types.ProcessListResult>;

  /**
   * Reload supervisor configuration from disk.
   * 
   * Returns:
   * True if reload succeeded
   */
  reloadConfig(): Promise<boolean>;

  /**
   * Remove a backend-to-host mapping.
   * 
   * Args:
   * backend_name: Name of the backend to unmap
   * 
   * Returns:
   * Success/failure result
   */
  removeBackendHost(backendName: string): Promise<Types.ConfigUpdateResult>;

  /**
   * Remove a host from the configuration.
   * 
   * Args:
   * host_name: Name of the host to remove
   * 
   * Returns:
   * Success/failure result
   */
  removeHost(hostName: string): Promise<Types.ConfigUpdateResult>;

  /**
   * Restart a backend server slot.
   * 
   * Args:
   * slot: "a" or "b" for slot A or B
   * 
   * Returns:
   * Success/failure result
   * 
   * Note: This triggers a restart of the server via balloons-server.py.
   * The WebSocket connection will be lost and the client should reconnect.
   */
  restartBackend(slot: string): Promise<Types.ConfigUpdateResult>;

  /**
   * Restart the bun dev server (UI).
   * 
   * Returns:
   * Success/failure result
   */
  restartUi(): Promise<Types.ConfigUpdateResult>;

  /**
   * Send input to a running process's stdin.
   * 
   * Args:
   * process_id: The process ID to send input to
   * data: The input data to send (newline is appended automatically)
   * 
   * Returns:
   * Success/failure result
   */
  sendProcessInput(processId: string, data: string): Promise<Types.ConfigUpdateResult>;

  /**
   * Map a backend to a host.
   * 
   * Args:
   * backend_name: Name of the LLM backend
   * host_name: Name of the host it runs on
   * 
   * Returns:
   * Success/failure result
   */
  setBackendHost(backendName: string, hostName: string): Promise<Types.ConfigUpdateResult>;

  /**
   * Stop a running supervised process.
   * 
   * Args:
   * process_id: The process ID to stop
   * 
   * Returns:
   * Success/failure result
   */
  stopProcess(processId: string): Promise<Types.ConfigUpdateResult>;

  /**
   * Update an existing host in the configuration.
   * 
   * Args:
   * request: Host configuration (name must exist, or originalName for rename)
   * 
   * Returns:
   * Success/failure result
   */
  updateHost(request: Types.HostUpdateRequest | Record<string, unknown>): Promise<Types.ConfigUpdateResult>;

}

export interface SupervisorStateEvents {
  /**
   * Fired when a host's status changes.
   */
  hostStatusChanged(callback: (data: Types.HostInfo) => void): Unsubscribe;

  /**
   * Fired when a process emits output (stdout/stderr).
   */
  processOutput(callback: (data: Types.ProcessOutput) => void): Unsubscribe;

  /**
   * Fired when a new process starts.
   */
  processStarted(callback: (data: Types.ProcessInfo) => void): Unsubscribe;

  /**
   * Fired when a process stops.
   */
  processStopped(callback: (data: Types.ProcessInfo) => void): Unsubscribe;

  /**
   * Fired when supervisor state changes (processes started/stopped, etc).
   */
  supervisorStateUpdated(callback: (data: Types.SupervisorState) => void): Unsubscribe;

}

export class SupervisorStateServiceClient implements SupervisorStateService {
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
    const id = generateRequestId();
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

  async addHost(request: Types.HostUpdateRequest | Record<string, unknown>): Promise<Types.ConfigUpdateResult> {
    return this.call('addHost', { request: request });
  }

  async checkHostStatus(hostName: string): Promise<Types.HostStatusResult> {
    return this.call('checkHostStatus', { hostName: hostName });
  }

  async getProcessOutput(processId: string, limit?: number, offset?: number, source?: string | null): Promise<Types.ProcessOutputBatch> {
    return this.call('getProcessOutput', { processId: processId, limit: limit, offset: offset, source: source });
  }

  async getServerStatus(): Promise<Record<string, unknown>> {
    return this.call('getServerStatus', {  });
  }

  async getState(): Promise<Types.SupervisorState> {
    return this.call('getState', {  });
  }

  async listHosts(tags?: string[] | null, hostType?: string | null): Promise<Types.HostQueryResult> {
    return this.call('listHosts', { tags: tags, hostType: hostType });
  }

  async listProcesses(sessionId?: string | null, host?: string | null, processType?: string | null): Promise<Types.ProcessListResult> {
    return this.call('listProcesses', { sessionId: sessionId, host: host, processType: processType });
  }

  async reloadConfig(): Promise<boolean> {
    return this.call('reloadConfig', {  });
  }

  async removeBackendHost(backendName: string): Promise<Types.ConfigUpdateResult> {
    return this.call('removeBackendHost', { backendName: backendName });
  }

  async removeHost(hostName: string): Promise<Types.ConfigUpdateResult> {
    return this.call('removeHost', { hostName: hostName });
  }

  async restartBackend(slot: string): Promise<Types.ConfigUpdateResult> {
    return this.call('restartBackend', { slot: slot });
  }

  async restartUi(): Promise<Types.ConfigUpdateResult> {
    return this.call('restartUi', {  });
  }

  async sendProcessInput(processId: string, data: string): Promise<Types.ConfigUpdateResult> {
    return this.call('sendProcessInput', { processId: processId, data: data });
  }

  async setBackendHost(backendName: string, hostName: string): Promise<Types.ConfigUpdateResult> {
    return this.call('setBackendHost', { backendName: backendName, hostName: hostName });
  }

  async stopProcess(processId: string): Promise<Types.ConfigUpdateResult> {
    return this.call('stopProcess', { processId: processId });
  }

  async updateHost(request: Types.HostUpdateRequest | Record<string, unknown>): Promise<Types.ConfigUpdateResult> {
    return this.call('updateHost', { request: request });
  }

  hostStatusChanged(callback: (data: Types.HostInfo) => void): Unsubscribe {
    return this.subscribe('hostStatusChanged', callback);
  }

  processOutput(callback: (data: Types.ProcessOutput) => void): Unsubscribe {
    return this.subscribe('processOutput', callback);
  }

  processStarted(callback: (data: Types.ProcessInfo) => void): Unsubscribe {
    return this.subscribe('processStarted', callback);
  }

  processStopped(callback: (data: Types.ProcessInfo) => void): Unsubscribe {
    return this.subscribe('processStopped', callback);
  }

  supervisorStateUpdated(callback: (data: Types.SupervisorState) => void): Unsubscribe {
    return this.subscribe('supervisorStateUpdated', callback);
  }

}

/**
 * WebSocket-exposed service for browser management.
 * 
 * Provides:
 * - Browser lifecycle: create, destroy, list, rename
 * - Browser control: goto, see, click, fill, screenshot
 * - Real-time events for browser state changes
 */
export interface BrowserStateService {
  /**
   * Navigate back.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  back(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Get all button elements.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with button elements as JSON in data field
   */
  buttons(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Click an element.
   * 
   * Args:
   * selector: CSS selector for element to click
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  click(selector: string, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Click a button by index.
   * 
   * Args:
   * index: Button index (from buttons() result)
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  clickButton(index: number, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Close the current tab.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   * 
   * Note:
   * If this is the last tab, the browser will be closed.
   */
  closeTab(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Create a new browser instance.
   * 
   * Args:
   * name: Browser name (auto-generated if not provided)
   * browser_type: Browser type ("chrome", "firefox")
   * headless: Run in headless mode
   * webdriver_url: Optional WebDriver URL
   * port: Optional port for WebDriver
   * set_as_default: Set this browser as the default
   * 
   * Returns:
   * BrowserResult with the created browser info
   */
  createBrowser(name?: string | null, browserType?: string, headless?: boolean, webdriverUrl?: string | null, port?: number | null, setAsDefault?: boolean): Promise<Types.BrowserResult>;

  /**
   * Destroy a browser instance.
   * 
   * Args:
   * name: Browser name to destroy
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  destroyBrowser(name: string): Promise<Types.BrowserResult>;

  /**
   * Execute JavaScript.
   * 
   * Args:
   * script: JavaScript code to execute
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with result in data field
   */
  executeJs(script: string, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Fill an input field.
   * 
   * Args:
   * selector: CSS selector for input
   * text: Text to fill
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  fill(selector: string, text: string, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Navigate forward.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  forward(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Get a specific browser by name.
   * 
   * Args:
   * name: Browser name
   * 
   * Returns:
   * BrowserResult with the browser info
   */
  getBrowser(name: string): Promise<Types.BrowserResult>;

  /**
   * Get page title.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with title in data field
   */
  getTitle(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Get current URL.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with URL in data field
   */
  getUrl(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Navigate to a URL.
   * 
   * Args:
   * url: URL to navigate to
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserNavigateResult with current URL and title
   */
  goto(url: string, name?: string | null): Promise<Types.BrowserNavigateResult>;

  /**
   * Get all input elements.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with input elements as JSON in data field
   */
  inputs(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Get all links.
   * 
   * Args:
   * limit: Maximum number of links to return
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with links as JSON in data field
   */
  links(limit?: number | null, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * List all browser instances.
   * 
   * Returns:
   * BrowserListResult with all browsers and default browser name
   */
  listBrowsers(): Promise<Types.BrowserListResult>;

  /**
   * List all tabs in a browser.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * TabListResult with list of tabs
   */
  listTabs(name?: string | null): Promise<Types.TabListResult>;

  /**
   * Open a new tab.
   * 
   * Args:
   * url: URL to navigate to (optional)
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult with the new tab handle in data field
   */
  newTab(url?: string | null, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Refresh the page.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  refresh(name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Rename a browser instance.
   * 
   * Args:
   * old_name: Current browser name
   * new_name: New browser name
   * 
   * Returns:
   * BrowserResult with updated browser info
   */
  renameBrowser(oldName: string, newName: string): Promise<Types.BrowserResult>;

  /**
   * Take a screenshot.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * save_to_file: If True, save to a temp file and return path instead of data URL
   * 
   * Returns:
   * BrowserScreenshotResult with base64-encoded PNG data URL or file path
   */
  screenshot(name?: string | null, saveToFile?: boolean): Promise<Types.BrowserScreenshotResult>;

  /**
   * Get structured page content.
   * 
   * Args:
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserSeeResult with page structure as JSON
   */
  see(name?: string | null): Promise<Types.BrowserSeeResult>;

  /**
   * Set the default browser.
   * 
   * Args:
   * name: Browser name to set as default
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  setDefault(name: string): Promise<Types.BrowserResult>;

  /**
   * Set an input value by index.
   * 
   * Args:
   * index: Input index (from inputs() result)
   * value: Value to set
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  setInput(index: number, value: string, name?: string | null): Promise<Types.BrowserResult>;

  /**
   * Switch to a specific tab.
   * 
   * Args:
   * handle: Window handle of the tab to switch to
   * name: Browser name (uses default if not specified)
   * 
   * Returns:
   * BrowserResult indicating success/failure
   */
  switchTab(handle: string, name?: string | null): Promise<Types.BrowserResult>;

}

export interface BrowserStateEvents {
  /**
   * Fired when a new browser is created.
   */
  browserCreated(callback: (data: Types.BrowserInfo) => void): Unsubscribe;

  /**
   * Fired when a browser is destroyed.
   */
  browserDestroyed(callback: (data: Types.BrowserInfo) => void): Unsubscribe;

  /**
   * Fired when browser state changes (created, destroyed, navigated, etc).
   */
  browserEvent(callback: (data: Types.BrowserEvent) => void): Unsubscribe;

  /**
   * Fired when a browser navigates to a new URL.
   */
  browserNavigated(callback: (data: Types.BrowserInfo) => void): Unsubscribe;

}

export class BrowserStateServiceClient implements BrowserStateService {
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
    const id = generateRequestId();
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

  async back(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('back', { name: name });
  }

  async buttons(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('buttons', { name: name });
  }

  async click(selector: string, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('click', { selector: selector, name: name });
  }

  async clickButton(index: number, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('clickButton', { index: index, name: name });
  }

  async closeTab(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('closeTab', { name: name });
  }

  async createBrowser(name?: string | null, browserType?: string, headless?: boolean, webdriverUrl?: string | null, port?: number | null, setAsDefault?: boolean): Promise<Types.BrowserResult> {
    return this.call('createBrowser', { name: name, browserType: browserType, headless: headless, webdriverUrl: webdriverUrl, port: port, setAsDefault: setAsDefault });
  }

  async destroyBrowser(name: string): Promise<Types.BrowserResult> {
    return this.call('destroyBrowser', { name: name });
  }

  async executeJs(script: string, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('executeJs', { script: script, name: name });
  }

  async fill(selector: string, text: string, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('fill', { selector: selector, text: text, name: name });
  }

  async forward(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('forward', { name: name });
  }

  async getBrowser(name: string): Promise<Types.BrowserResult> {
    return this.call('getBrowser', { name: name });
  }

  async getTitle(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('getTitle', { name: name });
  }

  async getUrl(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('getUrl', { name: name });
  }

  async goto(url: string, name?: string | null): Promise<Types.BrowserNavigateResult> {
    return this.call('goto', { url: url, name: name });
  }

  async inputs(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('inputs', { name: name });
  }

  async links(limit?: number | null, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('links', { limit: limit, name: name });
  }

  async listBrowsers(): Promise<Types.BrowserListResult> {
    return this.call('listBrowsers', {  });
  }

  async listTabs(name?: string | null): Promise<Types.TabListResult> {
    return this.call('listTabs', { name: name });
  }

  async newTab(url?: string | null, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('newTab', { url: url, name: name });
  }

  async refresh(name?: string | null): Promise<Types.BrowserResult> {
    return this.call('refresh', { name: name });
  }

  async renameBrowser(oldName: string, newName: string): Promise<Types.BrowserResult> {
    return this.call('renameBrowser', { oldName: oldName, newName: newName });
  }

  async screenshot(name?: string | null, saveToFile?: boolean): Promise<Types.BrowserScreenshotResult> {
    return this.call('screenshot', { name: name, saveToFile: saveToFile });
  }

  async see(name?: string | null): Promise<Types.BrowserSeeResult> {
    return this.call('see', { name: name });
  }

  async setDefault(name: string): Promise<Types.BrowserResult> {
    return this.call('setDefault', { name: name });
  }

  async setInput(index: number, value: string, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('setInput', { index: index, value: value, name: name });
  }

  async switchTab(handle: string, name?: string | null): Promise<Types.BrowserResult> {
    return this.call('switchTab', { handle: handle, name: name });
  }

  browserCreated(callback: (data: Types.BrowserInfo) => void): Unsubscribe {
    return this.subscribe('browserCreated', callback);
  }

  browserDestroyed(callback: (data: Types.BrowserInfo) => void): Unsubscribe {
    return this.subscribe('browserDestroyed', callback);
  }

  browserEvent(callback: (data: Types.BrowserEvent) => void): Unsubscribe {
    return this.subscribe('browserEvent', callback);
  }

  browserNavigated(callback: (data: Types.BrowserInfo) => void): Unsubscribe {
    return this.subscribe('browserNavigated', callback);
  }

}

/**
 * WebSocket-exposed service for LSP server management.
 */
export interface LSPService {
  /**
   * Get all symbols in a document.
   * 
   * Uses the LSP textDocument/documentSymbol request.
   * The language server is automatically started if needed.
   * 
   * Args:
   * file_path: Absolute path to the file
   * 
   * Returns:
   * List of document symbols (hierarchical)
   */
  getDocumentSymbols(filePath: string): Promise<Types.LSPDocumentSymbolsResult>;

  /**
   * Get complete LSP status.
   * 
   * Returns configured servers and all running instances.
   */
  getStatus(): Promise<Types.LSPStatusResult>;

  /**
   * Restart an LSP server.
   * 
   * Args:
   * language: Language server name
   * workspace: Workspace root
   * key: Instance key (alternative to language+workspace)
   * 
   * Returns:
   * Action result with status
   */
  restartServer(language?: string | null, workspace?: string | null, key?: string | null): Promise<Types.LSPActionResult>;

  /**
   * Start an LSP server.
   * 
   * Args:
   * language: Language server name (e.g., "python")
   * workspace: Workspace root (defaults to cwd)
   * 
   * Returns:
   * Action result with status
   */
  startServer(language: string, workspace?: string | null): Promise<Types.LSPActionResult>;

  /**
   * Stop all running LSP servers.
   * 
   * Returns:
   * Number of servers stopped
   */
  stopAllServers(): Promise<number>;

  /**
   * Stop an LSP server.
   * 
   * Can specify by language+workspace or by key.
   * 
   * Args:
   * language: Language server name
   * workspace: Workspace root
   * key: Instance key (alternative to language+workspace)
   * 
   * Returns:
   * Action result with status
   */
  stopServer(language?: string | null, workspace?: string | null, key?: string | null): Promise<Types.LSPActionResult>;

}

export interface LSPEvents {
  /**
   * Fired when an LSP server restarts.
   */
  lspServerRestarted(callback: (data: Record<string, unknown>) => void): Unsubscribe;

  /**
   * Fired when an LSP server starts.
   */
  lspServerStarted(callback: (data: Record<string, unknown>) => void): Unsubscribe;

  /**
   * Fired when an LSP server stops.
   */
  lspServerStopped(callback: (data: Record<string, unknown>) => void): Unsubscribe;

}

export class LSPServiceClient implements LSPService {
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
    const id = generateRequestId();
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

  async getDocumentSymbols(filePath: string): Promise<Types.LSPDocumentSymbolsResult> {
    return this.call('getDocumentSymbols', { filePath: filePath });
  }

  async getStatus(): Promise<Types.LSPStatusResult> {
    return this.call('getStatus', {  });
  }

  async restartServer(language?: string | null, workspace?: string | null, key?: string | null): Promise<Types.LSPActionResult> {
    return this.call('restartServer', { language: language, workspace: workspace, key: key });
  }

  async startServer(language: string, workspace?: string | null): Promise<Types.LSPActionResult> {
    return this.call('startServer', { language: language, workspace: workspace });
  }

  async stopAllServers(): Promise<number> {
    return this.call('stopAllServers', {  });
  }

  async stopServer(language?: string | null, workspace?: string | null, key?: string | null): Promise<Types.LSPActionResult> {
    return this.call('stopServer', { language: language, workspace: workspace, key: key });
  }

  lspServerRestarted(callback: (data: Record<string, unknown>) => void): Unsubscribe {
    return this.subscribe('lspServerRestarted', callback);
  }

  lspServerStarted(callback: (data: Record<string, unknown>) => void): Unsubscribe {
    return this.subscribe('lspServerStarted', callback);
  }

  lspServerStopped(callback: (data: Record<string, unknown>) => void): Unsubscribe {
    return this.subscribe('lspServerStopped', callback);
  }

}

/**
 * WebSocket RPC service for domain plugin methods.
 * 
 * This service dynamically exposes domain methods marked with @ws_expose.
 * Methods are registered when domains are loaded and unregistered when unloaded.
 */
export interface DomainRpcService {
  /**
   * Call a domain method by wire name.
   * 
   * This is the generic dispatch endpoint. The generated client will also
   * create typed methods for each registered domain method.
   * 
   * Args:
   * method_name: The camelCase wire name of the method
   * session_id: The session ID for context
   * params: Method parameters
   * 
   * Returns:
   * {result: str} on success, {error: str} on failure
   */
  callDomainMethod(methodName: string, sessionId: string, params?: Record<string, unknown> | null): Promise<Record<string, unknown>>;

}

export class DomainRpcServiceClient implements DomainRpcService {
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
    const id = generateRequestId();
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

  async callDomainMethod(methodName: string, sessionId: string, params?: Record<string, unknown> | null): Promise<Record<string, unknown>> {
    return this.call('callDomainMethod', { methodName: methodName, sessionId: sessionId, params: params });
  }

}

