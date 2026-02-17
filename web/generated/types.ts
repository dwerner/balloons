// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_type decorators.
// Generated: 2026-02-16T15:21:26.941809
//
// To regenerate:
//     python -m codegen.generate_typescript
//
// To add new types, add @ws_type decorator to dataclasses in your service modules.

export interface SessionInfo {
  id: string;
  title: string;
  created: string;
  lastModified: string;
  model: string;
  messageCount: number;
  totalCost: number;
  isCurrent: boolean;
  isStreaming: boolean;
  forkName: string;
  forkStatus: string;
  parentId?: string | null;
  cachedContextTokens?: number;
  contextWindow?: number;
  bindingIndicator?: string;
}

export interface TurnImageInfo {
  filePath: string;
  filename: string;
  mediaType: string;
  width?: number;
  height?: number;
}

export interface ToolUseInfo {
  toolUseId: string;
  toolName: string;
  toolInput?: Record<string, unknown>;
}

export interface ToolResultInfo {
  toolUseId: string;
  content: string;
  isError?: boolean;
}

export interface TurnInfo {
  idx: number;
  role: string;
  content: string;
  streaming: boolean;
  viewed: boolean;
  tokens: number;
  contextMode: string;
  contentBlockType?: string;
  exchangeId?: string | null;
  images?: TurnImageInfo[];
  toolUse?: ToolUseInfo | null;
  toolResult?: ToolResultInfo | null;
}

export interface TreeEventData {
  eventType: string;
  sessionId: string;
  turnIdx?: number | null;
  data?: Record<string, unknown>;
}

export interface QueuedMessageInfo {
  id: string;
  content: string;
  created: string;
  paused: boolean;
  preview: string;
}

export interface QueueInfo {
  sessionId: string;
  messages: QueuedMessageInfo[];
  isBlocked: boolean;
  firstPauseIndex: number;
  messageCount: number;
}

export interface QueueEventData {
  eventType: string;
  sessionId: string;
  messageId?: string | null;
  data?: Record<string, unknown>;
}

export interface ManagedSessionInfo {
  id: string;
  title: string;
  created: string;
  model: string;
  messageCount: number;
  isActive: boolean;
  isStreaming: boolean;
  isChild: boolean;
  isReturned: boolean;
  parentId?: string | null;
  workingDirectory?: string;
}

export interface StreamingInfo {
  sessionId: string;
  streamId: string;
  status: string;
  backendName: string;
  startedAt: string;
  tokensStreamed: number;
  toolName?: string | null;
  toolCount?: number;
  inputTokens?: number;
  outputTokens?: number;
}

export interface SessionEventData {
  eventType: string;
  sessionId: string;
  data?: Record<string, unknown>;
}

export interface SubmitMessageResult {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  status: string;
}

export interface ImageAttachment {
  filePath: string;
  mediaType: string;
  filename?: string;
  width?: number;
  height?: number;
}

export interface GoalInfo {
  id: string;
  title: string;
  description: string;
  weight: number;
  status: string;
  acceptanceCriteria: string[];
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
  parentGoalId?: string | null;
  planIds?: string[];
  childGoalIds?: string[];
  boundSessionIds?: string[];
  isExpanded?: boolean;
}

export interface PlanInfo {
  id: string;
  goalId: string;
  title: string;
  description: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
  postmortem?: string | null;
  todoIds?: string[];
  boundSessionIds?: string[];
  isExpanded?: boolean;
}

export interface TodoInfo {
  id: string;
  title: string;
  description: string;
  status: string;
  isSpike: boolean;
  createdAt: string;
  updatedAt: string;
  completedAt?: string | null;
  timeboxMinutes?: number | null;
  planIds?: string[];
  boundSessionIds?: string[];
  dependencyIds?: string[];
  isExpanded?: boolean;
  priority?: number;
}

export interface SessionBindingInfo {
  sessionId: string;
  name: string;
  tokenCount: number;
  isCurrent: boolean;
  isStreaming: boolean;
  forkStatus: string;
  bindingRole: string;
}

export interface GoalTreeStats {
  totalGoals: number;
  activeGoals: number;
  totalPlans: number;
  activePlans: number;
  totalTodos: number;
  pendingTodos: number;
  inProgressTodos: number;
  boundSessions: number;
  unboundSessions: number;
}

export interface GoalProgress {
  completed: number;
  total: number;
}

export interface SelectedEntity {
  entityType: string;
  entityId: string;
}

export interface GoalTreeEventData {
  eventType: string;
  entityType?: string | null;
  entityId?: string | null;
  data?: Record<string, unknown>;
}

export interface SmartTodoResult {
  success: boolean;
  message: string;
  todoId?: string | null;
  todoTitle?: string | null;
  planId?: string | null;
  planTitle?: string | null;
  goalId?: string | null;
  goalTitle?: string | null;
}

export interface TaskInfo {
  taskId: string;
  taskType: string;
  status: string;
  sessionId: string | null;
  backendName: string;
  startedAt: string;
  finishedAt: string | null;
  prompt: string;
  tokensStreamed: number;
  error: string | null;
  toolName: string | null;
  toolCount: number;
  inputTokens: number;
  outputTokens: number;
  contextWindow: number;
  model: string;
  durationSeconds: number;
  isActive: boolean;
  currentTokenRate: number;
}

export interface SessionTaskSummary {
  sessionId: string;
  sessionTitle: string;
  backendName: string;
  isStreaming: boolean;
  hasActiveTask: boolean;
  totalExchanges: number;
  lastActivity: string | null;
}

export interface TaskEventData {
  eventType: string;
  taskId: string;
  taskType: string;
  status: string;
  sessionId?: string | null;
  error?: string | null;
  data?: Record<string, unknown>;
}

export interface BackendSummary {
  backendName: string;
  activeCount: number;
}

export interface ContentDeltaEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  delta: string;
  accumulated: string;
}

export interface TurnStartedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  role: string;
  turnType?: string | null;
}

export interface TurnFinishedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  role: string;
  content: string;
}

export interface ToolUseStartedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  toolUseId: string;
  toolName: string;
  toolIndex: number;
}

export interface ToolInputDeltaEvent {
  sessionId: string;
  exchangeId: string;
  toolUseId: string;
  partialJson: string;
}

export interface ToolUseEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  toolUseId: string;
  toolName: string;
  toolInput: Record<string, unknown>;
  toolIndex: number;
}

export interface ToolResultEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  toolUseId: string;
  toolName: string;
  result: string;
  isError: boolean;
  toolIndex: number;
}

export interface ImageUploadResult {
  filePath: string;
  filename: string;
  mediaType: string;
  sizeBytes: number;
  width?: number;
  height?: number;
}

export interface ImageInfo {
  filePath: string;
  filename: string;
  mediaType: string;
  sizeBytes: number;
  createdAt: string;
  sessionId?: string | null;
}

export interface ImageEventData {
  eventType: string;
  filePath: string;
  data?: Record<string, unknown>;
}

