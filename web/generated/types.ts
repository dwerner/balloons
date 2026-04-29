// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_type decorators.
// Generated: 2026-04-29T09:18:19.008575
//
// To regenerate:
//     python -m codegen.generate_typescript
//
// To add new types, add @ws_type decorator to dataclasses in your service modules.

export interface TextBlock {
  type?: string;
  text?: string;
}

export interface MarkdownBlock {
  type?: string;
  text?: string;
}

export interface ThinkingBlock {
  type?: string;
  text?: string;
}

export interface ImageBlock {
  type?: string;
  filePath?: string;
  mediaType?: string;
  filename?: string;
  width?: number;
  height?: number;
}

export interface ToolUseBlock {
  type?: string;
  id?: string;
  name?: string;
  input?: Record<string, unknown>;
}

export interface ToolResultBlock {
  type?: string;
  toolUseId?: string;
  content?: string;
  isError?: boolean;
}

export interface RepairedToolBlock {
  type?: string;
  toolUseId?: string;
  toolName?: string;
  originalInput?: string;
  repairedInput?: string;
  repairDescription?: string;
  repairSuccessful?: boolean;
}

export interface InterruptionBlock {
  type?: string;
  reason?: string;
}

export interface ErrorBlock {
  type?: string;
  reason?: string;
  partialToolName?: string;
  partialToolInput?: string;
  details?: string;
  dumpFile?: string;
}

export interface LinkBlock {
  type?: string;
  linkId?: string;
  linkedSessionId?: string;
  summary?: string;
  isOrphaned?: boolean;
}

export interface ForkBlock {
  type?: string;
  forkId?: string;
  childSessionId?: string;
  forkName?: string;
  prompt?: string;
  status?: string;
}

export interface MergeBlock {
  type?: string;
  mergeId?: string;
  childSessionId?: string;
  forkName?: string;
  message?: string;
  filesChanged?: string[];
  keyAccomplishments?: string[];
  reason?: string;
}

export interface MergedToBlock {
  type?: string;
  mergeId?: string;
  parentSessionId?: string;
  parentName?: string;
  parentTurn?: number;
  message?: string;
  filesChanged?: string[];
  keyAccomplishments?: string[];
  reason?: string;
}

export interface ForkedFromBlock {
  type?: string;
  forkId?: string;
  parentSessionId?: string;
  parentName?: string;
  parentTurn?: number;
  forkName?: string;
  prompt?: string;
}

export interface SlideBlock {
  type?: string;
  title?: string;
  content?: string;
  notes?: string;
}

export interface ReviewBlock {
  type?: string;
  reviewId?: string;
  childSessionId?: string;
  modelUnderReview?: string;
  status?: string;
  overallScore?: number;
  taskCategory?: string;
  taskDescription?: string;
  notes?: string;
}

export interface ContextAssignmentData {
  exchangeRange?: string;
  mode?: string;
  reason?: string;
}

export interface ExchangeInfo {
  index?: number;
  summary?: string;
  mode?: string;
}

export interface ForkBindingData {
  entityType?: string;
  entityId?: string;
  role?: string;
}

export interface ForkProposalBlock {
  type?: string;
  proposalId?: string;
  name?: string;
  description?: string;
  contextPlan?: ContextAssignmentData[];
  initialPrompt?: string;
  bindTo?: ForkBindingData | null;
  bindToInherit?: boolean;
  status?: string;
  allExchanges?: ExchangeInfo[];
  childSessionId?: string;
}

export interface MergeProposalBlock {
  type?: string;
  proposalId?: string;
  summary?: string;
  reason?: string;
  filesChanged?: string[];
  keyAccomplishments?: string[];
  status?: string;
}

export interface ArchiveSummary {
  filesModified?: string[];
  workDone?: string;
  keyDecisions?: string[];
}

export interface ArchiveBlock {
  type?: string;
  archiveId?: string;
  filePath?: string;
  summary?: string;
  structuredSummary?: ArchiveSummary | null;
  turnStart?: number;
  turnEnd?: number;
  messageCount?: number;
  tokenEstimate?: number;
}

export interface SessionSummaryBlock {
  type?: string;
  summaryId?: string;
  proposedTitle?: string;
  markdownContent?: string;
  filesModified?: string[];
  decisionsMade?: string[];
  workDone?: string;
  nextSteps?: string[];
  questionsRaised?: string[];
  turnCountAtReview?: number;
  reviewedAt?: string;
  reviewedByBackend?: string;
  status?: string;
  approvedTitle?: string;
}

export interface WatchStartBlock {
  type?: string;
  targetSessionId?: string;
  targetSessionName?: string;
}

export interface WatchStopBlock {
  type?: string;
  targetSessionId?: string;
  reason?: string;
}

export interface WatchSummaryBlock {
  type?: string;
  targetSessionId?: string;
  targetSessionName?: string;
  exchangeIndex?: number;
  summary?: string;
}

export interface ThinkingBlock {
  type?: string;
  text?: string;
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

export interface SteeringInjectedEvent {
  sessionId: string;
  exchangeId: string;
  content: string;
  injectedAtToolId: string;
}

export interface HelperStartedEvent {
  helperId: string;
  helperType: string;
  sessionId?: string | null;
  metadata?: Record<string, unknown>;
}

export interface HelperDeltaEvent {
  helperId: string;
  helperType: string;
  delta: string;
  accumulatedLength: number;
  sessionId?: string | null;
}

export interface HelperDoneEvent {
  helperId: string;
  helperType: string;
  result: string;
  sessionId?: string | null;
  metadata?: Record<string, unknown>;
}

export interface HelperErrorEvent {
  helperId: string;
  helperType: string;
  sessionId?: string | null;
  error?: string | null;
  cancelled?: boolean;
}

export interface DomainEventWrapper {
  domainId: string;
  eventType: string;
  sessionId: string;
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

export interface ForkSessionResult {
  success: boolean;
  childSessionId?: string;
  parentSessionId?: string;
  forkName?: string;
  exchangeId?: string;
  needsCompression?: boolean;
  helperId?: string;
  error?: string;
}

export interface MergeSessionResult {
  success: boolean;
  forkSessionId?: string;
  parentSessionId?: string;
  mergeId?: string;
  mergePoint?: number;
  error?: string;
}

export interface ConcludeSessionResult {
  success: boolean;
  sessionId?: string;
  concludedAt?: string;
  reason?: string;
  turnIndex?: number;
  error?: string;
}

export interface DeriveSessionResult {
  success: boolean;
  newSessionId?: string;
  sourceSessionId?: string;
  exchangeId?: string;
  needsCompression?: boolean;
  helperId?: string;
  error?: string;
}

export interface LinkSessionsResult {
  success: boolean;
  linkId?: string;
  sourceSessionId?: string;
  targetSessionId?: string;
  error?: string;
}

export interface SwitchTargetResult {
  success: boolean;
  targetSessionId?: string;
  availableForks?: Record<string, unknown>[];
  error?: string;
}

export interface ContextModeItem {
  turnIndex: number;
  mode: string;
}

export interface ExchangeSummary {
  index: number;
  summary: string;
  mode?: string;
}

export interface PromptComponentInfo {
  id: string;
  name: string;
  description: string;
  tokens: number;
  enabled?: boolean;
  contentPreview?: string;
  fullContent?: string;
}

export interface DomainInfoItem {
  id: string;
  name: string;
  loaded: boolean;
  promptTokens: number;
  contextTokens: number;
  tools?: string[];
  promptContent?: string;
}

export interface SessionPromptFileInfo {
  filePath: string;
  filename: string;
  tokens: number;
  exists?: boolean;
  contentPreview?: string;
  fullContent?: string;
}

export interface SystemPromptInfoResult {
  components?: PromptComponentInfo[];
  domains?: DomainInfoItem[];
  sessionPromptFiles?: SessionPromptFileInfo[];
  totalTokens?: number;
  contextWindow?: number;
  backendType?: string;
}

export interface RespondToForkProposalResult {
  success: boolean;
  accepted?: boolean;
  childSessionId?: string;
  parentSessionId?: string;
  forkName?: string;
  exchangeId?: string;
  needsCompression?: boolean;
  helperId?: string;
  error?: string;
}

export interface RespondToMergeProposalResult {
  success: boolean;
  accepted?: boolean;
  forkSessionId?: string;
  parentSessionId?: string;
  mergeId?: string;
  mergePoint?: number;
  error?: string;
}

export interface ImageAttachment {
  filePath: string;
  mediaType: string;
  filename?: string;
  width?: number;
  height?: number;
}

export interface StartArchiveResult {
  success: boolean;
  helperId?: string;
  sessionId?: string;
  turnStart?: number;
  turnEnd?: number;
  error?: string;
}

export interface CompleteArchiveResult {
  success: boolean;
  sessionId?: string;
  archiveId?: string;
  turnIndex?: number;
  turnsArchived?: number;
  helperId?: string;
  error?: string;
}

export interface RehydrateResult {
  success: boolean;
  sessionId?: string;
  turnIndex?: number;
  turnsRestored?: number;
  error?: string;
}

export interface StartSessionReviewResult {
  success: boolean;
  helperId?: string;
  sessionId?: string;
  backendName?: string;
  error?: string;
}

export interface CompleteSessionReviewResult {
  success: boolean;
  sessionId?: string;
  summaryId?: string;
  turnIndex?: number;
  proposedTitle?: string;
  markdownContent?: string;
  error?: string;
}

export interface ApproveSessionReviewResult {
  success: boolean;
  sessionId?: string;
  summaryId?: string;
  approvedTitle?: string;
  error?: string;
}

export interface GenerateCommitMessageResult {
  success: boolean;
  helperId?: string;
  error?: string;
}

export interface CreateWatcherSessionResult {
  success: boolean;
  watcherSessionId?: string;
  targetSessionId?: string;
  targetSessionName?: string;
  watcherName?: string;
  error?: string;
}

export interface RequestProposalResult {
  success: boolean;
  sessionId?: string;
  exchangeId?: string;
  turnIndex?: number;
  error?: string;
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
  turnId: string;
  delta: string;
  accumulated: string;
}

export interface TurnStartedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  turnId: string;
  role: string;
  turnType?: string | null;
  parallelGroupId?: string | null;
}

export interface TurnFinishedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  turnId: string;
  role: string;
  content: string;
  parallelGroupId?: string | null;
}

export interface ToolUseStartedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  turnId: string;
  toolUseId: string;
  toolName: string;
  toolIndex: number;
  parallelGroupId?: string | null;
}

export interface ToolInputDeltaEvent {
  sessionId: string;
  exchangeId: string;
  turnId: string;
  toolUseId: string;
  partialJson: string;
}

export interface ToolUseEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  turnId: string;
  toolUseId: string;
  toolName: string;
  toolInput: Record<string, unknown>;
  toolIndex: number;
  parallelGroupId?: string | null;
}

export interface ToolResultEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  turnId: string;
  toolUseId: string;
  toolName: string;
  result: string;
  isError: boolean;
  toolIndex: number;
  parallelGroupId?: string | null;
}

export interface ToolResultDeltaEvent {
  sessionId: string;
  exchangeId: string;
  turnId: string;
  toolUseId: string;
  toolName: string;
  delta: string;
  stream: string;
}

export interface TurnDelta {
  sessionId: string;
  turnId: string;
  delta: string;
  accumulatedLength: number;
  exchangeId?: string | null;
}

export interface TurnSnapshot {
  turnId: string;
  role: string;
  streaming: boolean;
  viewed: boolean;
  tokens: number;
  contextMode: string;
  contentBlock: TextBlock | MarkdownBlock | ImageBlock | ToolUseBlock | ToolResultBlock | InterruptionBlock | ErrorBlock | LinkBlock | ForkBlock | ForkedFromBlock | MergeBlock | MergedToBlock | ArchiveBlock | SlideBlock | ReviewBlock | ForkProposalBlock | MergeProposalBlock | WatchStartBlock | WatchStopBlock | WatchSummaryBlock;
  order?: number;
  exchangeId?: string | null;
  timestamp?: string | null;
  parallelGroupId?: string | null;
  isSteering?: boolean;
  respondsToSteering?: boolean;
}

export interface SessionSnapshot {
  sessionId: string;
  title: string;
  model: string;
  isStreaming: boolean;
  turns?: TurnSnapshot[];
  streamingTurnIds?: string[];
}

export interface SubscriptionResult {
  sessionId: string;
  subscribed: boolean;
  error?: string | null;
  totalTurns?: number | null;
  isStreaming?: boolean | null;
}

export interface SubscribeSessionResult {
  sessionId: string;
  subscribed: boolean;
  snapshot?: SessionSnapshot | null;
  error?: string | null;
}

export interface SessionTurnCreatedEvent {
  sessionId: string;
  turnId: string;
  role: string;
  order: number;
  exchangeId?: string | null;
  contentBlockType?: string;
  parallelGroupId?: string | null;
  isSteering?: boolean;
}

export interface SessionTurnDeltaEvent {
  sessionId: string;
  turnId: string;
  delta: string;
  accumulatedLength: number;
  contentBlockType?: string;
}

export interface SessionTurnFinishedEvent {
  sessionId: string;
  turnId: string;
  tokens: number;
  order?: number;
  role?: string;
  contentBlock?: TextBlock | MarkdownBlock | ImageBlock | ToolUseBlock | ToolResultBlock | InterruptionBlock | ErrorBlock | LinkBlock | ForkBlock | ForkedFromBlock | MergeBlock | MergedToBlock | ArchiveBlock | SlideBlock | ReviewBlock | ForkProposalBlock | MergeProposalBlock | WatchStartBlock | WatchStopBlock | WatchSummaryBlock | null;
  finalContent?: string;
  contextTokens?: number;
  outputTokensTotal?: number;
}

export interface SessionTurnsDeletedEvent {
  sessionId: string;
  turnIndices: number[];
  turnIds: string[];
}

export interface TurnOrderMapping {
  turnId: string;
  newOrder: number;
}

export interface SessionTurnsReorderedEvent {
  sessionId: string;
  mappings: TurnOrderMapping[];
}

export interface SessionStreamStartedEvent {
  sessionId: string;
  exchangeId: string;
}

export interface SessionStreamDoneEvent {
  sessionId: string;
  exchangeId: string;
  inputTokens: number;
  outputTokens: number;
}

export interface SessionStreamProgressEvent {
  sessionId: string;
  exchangeId: string;
  tokensStreamed: number;
  currentTokenRate: number;
  toolName: string | null;
  toolCount: number;
  model: string;
  contextWindow: number;
  durationSeconds: number;
}

export interface SessionStreamErrorEvent {
  sessionId: string;
  exchangeId: string;
  error: string;
  errorType: string;
  dumpFile?: string;
}

export interface SessionToolUseStartedEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  toolUseId: string;
  toolName: string;
  toolIndex: number;
}

export interface SessionToolInputDeltaEvent {
  sessionId: string;
  exchangeId: string;
  toolUseId: string;
  partialJson: string;
}

export interface SessionToolUseEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  toolUseId: string;
  toolName: string;
  toolInput: Record<string, unknown>;
  toolIndex: number;
}

export interface SessionToolResultEvent {
  sessionId: string;
  exchangeId: string;
  turnIndex: number;
  toolUseId: string;
  toolName: string;
  result: string;
  isError: boolean;
  toolIndex: number;
}

export interface SessionToolResultDeltaEvent {
  sessionId: string;
  exchangeId: string;
  toolUseId: string;
  toolName: string;
  delta: string;
  stream: string;
}

export interface SessionDomainEvent {
  sessionId: string;
  domainId: string;
  eventType: string;
  data: Record<string, unknown>;
}

export interface SessionHistoryChunkEvent {
  sessionId: string;
  chunkId: string;
  turns: TurnSnapshot[];
  chunkIndex: number;
  totalChunks: number;
  watermark: number;
  reversed?: boolean;
}

export interface SessionHistoryCompleteEvent {
  sessionId: string;
  totalTurns: number;
  finalWatermark: number;
}

export interface ForkChild {
  sessionId: string;
  name: string;
  status: string;
  forkPoint: number;
}

export interface ForkTreeNode {
  sessionId: string;
  name: string;
  status: string;
  isCurrent: boolean;
  children?: ForkTreeNode[];
  watchTargets?: string[];
  watchedBy?: string[];
}

export interface SessionInfo {
  id: string;
  title: string;
  created: string;
  lastModified: string;
  model: string;
  messageCount: number;
  totalCost: number;
  isStreaming: boolean;
  forkName: string;
  forkStatus: string;
  concluded?: boolean;
  concludedAt?: string | null;
  parentId?: string | null;
  cachedContextTokens?: number;
  contextWindow?: number;
  bindingIndicator?: string;
  backendName?: string;
  isPinned?: boolean;
  workingDirectory?: string;
  children?: ForkChild[];
  watchTargets?: string[];
  watchedBy?: string[];
}

export interface SessionWatcherInfo {
  sessionId: string;
  watchTargets?: string[];
  watchedBy?: string[];
}

export interface SessionAddedEvent {
  sessionId: string;
  session: SessionInfo;
}

export interface SessionUpdatedEvent {
  sessionId: string;
  session: SessionInfo;
}

export interface SessionRemovedEvent {
  sessionId: string;
}

export interface SessionPinnedEvent {
  sessionId: string;
  isPinned: boolean;
}

export interface PinnedSessionsChangedEvent {
  pinnedSessionIds: string[];
}

export interface ToolUseInfo {
  toolUseId: string;
  name: string;
  inputJson: string;
}

export interface ToolResultInfo {
  toolUseId: string;
  content: string;
  isError?: boolean;
}

export interface TurnImageInfo {
  sourceType: string;
  mediaType: string;
  data: string;
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

export interface FileEntry {
  name: string;
  path: string;
  relativePath: string;
  isDirectory: boolean;
  size: number;
  modified: string;
  gitStatus: string;
  isStaged: boolean;
  isIgnored: boolean;
  childrenCount?: number | null;
}

export interface DirectoryListing {
  path: string;
  entries: FileEntry[];
  gitRoot?: string | null;
  gitPath?: string | null;
}

export interface SessionCwd {
  sessionId: string;
  cwd: string;
}

export interface CwdChangedData {
  sessionId: string;
  oldCwd: string | null;
  newCwd: string;
}

export interface FileOperationResult {
  success: boolean;
  message: string;
  path?: string | null;
}

export interface DiffChange {
  type: string;
  oldLineNumber: number | null;
  newLineNumber: number | null;
  content: string;
}

export interface DiffHunk {
  header: string;
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  changes: DiffChange[];
}

export interface DiffFile {
  path: string;
  absolutePath: string;
  oldPath: string | null;
  status: string;
  additions: number;
  deletions: number;
  isBinary: boolean;
  hunks: DiffHunk[];
}

export interface GitDiffResult {
  gitRoot: string;
  files: DiffFile[];
  hasUnstaged: boolean;
  hasStaged: boolean;
}

export interface UntrackedFile {
  path: string;
  absolutePath: string;
}

export interface WorkingTreeStatus {
  gitRoot: string;
  stagedFiles: DiffFile[];
  unstagedFiles: DiffFile[];
  untrackedFiles: UntrackedFile[];
}

export interface LogEntryInput {
  level: string;
  message: string;
  category?: string;
  sessionId?: string;
  details?: Record<string, unknown> | null;
}

export interface LogResult {
  success: boolean;
  seq?: number;
}

export interface LogEntryOutput {
  seq: number;
  timestamp: string;
  level: string;
  message: string;
  category: string;
  sessionId: string;
  runId: string;
  details: Record<string, unknown>;
}

export interface QueryResult {
  entries: LogEntryOutput[];
  total: number;
}

export interface BufferStats {
  category: string;
  count: number;
  maxsize: number;
}

export interface ServerIdentityInfo {
  gitCommit: string;
  gitCommitShort: string;
  gitBranch: string;
  gitDirty: boolean;
  gitDiffHash: string;
  slot: string;
  port: number;
  pid: number;
  startTime: string;
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

export interface SoundInfo {
  filename: string;
  mediaType: string;
  sizeBytes: number;
  isBuiltin?: boolean;
}

export interface SoundData {
  filename: string;
  mediaType: string;
  dataBase64: string;
}

export interface SoundUploadResult {
  filename: string;
  mediaType: string;
  sizeBytes: number;
  success: boolean;
  error?: string | null;
}

export interface SoundEventData {
  eventType: string;
  filename: string;
  data?: Record<string, unknown>;
}

export interface HostInfo {
  name: string;
  type: string;
  host?: string | null;
  user?: string | null;
  port?: number;
  tags?: string[];
  description?: string | null;
  status?: string;
  latencyMs?: number | null;
  error?: string | null;
}

export interface ProcessInfo {
  processId: string;
  command: string;
  name: string | null;
  host: string;
  sessionId: string;
  status: string;
  exitCode?: number | null;
  startedAt?: string | null;
  runtimeSeconds?: number | null;
  processType?: string;
}

export interface ProcessOutput {
  processId: string;
  source: string;
  content: string;
  ts: number;
}

export interface ProcessLogEntry {
  ts: number;
  source: string;
  content: string;
}

export interface ProcessOutputBatch {
  processId: string;
  entries: ProcessLogEntry[];
  totalCount: number;
  hasMore: boolean;
}

export interface BackendHostMapping {
  backendName: string;
  hostName: string;
}

export interface SupervisorState {
  hosts: HostInfo[];
  processes: ProcessInfo[];
  backendHosts: BackendHostMapping[];
}

export interface HostQueryResult {
  hosts: HostInfo[];
}

export interface HostStatusResult {
  host: string;
  type: string;
  status: string;
  latencyMs?: number | null;
  error?: string | null;
}

export interface ProcessListResult {
  summary: string;
  processes: ProcessInfo[];
}

export interface HostUpdateRequest {
  name: string;
  type?: string;
  host?: string | null;
  user?: string | null;
  port?: number;
  tags?: string[];
  description?: string | null;
  originalName?: string | null;
}

export interface ConfigUpdateResult {
  success: boolean;
  error?: string | null;
}

export interface SupervisorEvent {
  ts: number;
  type: string;
  data: Record<string, unknown>;
}

export interface EventHistoryResult {
  events: SupervisorEvent[];
  totalBuffered: number;
}

export interface BrowserInfo {
  name: string;
  browserId: string;
  browserType: string;
  headless: boolean;
  status: string;
  currentUrl?: string | null;
  currentTitle?: string | null;
  createdAt?: number;
  error?: string | null;
}

export interface BrowserListResult {
  browsers: BrowserInfo[];
  defaultBrowser?: string | null;
}

export interface BrowserCreateRequest {
  name?: string | null;
  browserType?: string;
  headless?: boolean;
  webdriverUrl?: string | null;
  port?: number | null;
  setAsDefault?: boolean;
}

export interface BrowserResult {
  success: boolean;
  browser?: BrowserInfo | null;
  error?: string | null;
  data?: string | null;
}

export interface BrowserNavigateResult {
  success: boolean;
  url?: string | null;
  title?: string | null;
  error?: string | null;
}

export interface BrowserScreenshotResult {
  success: boolean;
  dataUrl?: string | null;
  error?: string | null;
}

export interface BrowserSeeResult {
  success: boolean;
  content?: string | null;
  error?: string | null;
}

export interface BrowserEvent {
  browserName: string;
  eventType: string;
  browser?: BrowserInfo | null;
  url?: string | null;
  title?: string | null;
  ts?: number;
}

export interface LSPServerConfig {
  name: string;
  command: string;
  extensions: string[];
  languages: string[];
  idleTimeoutSeconds: number;
}

export interface LSPServerInstance {
  key: string;
  serverName: string;
  workspace: string;
  processId: string;
  initialized: boolean;
  idleSeconds: number;
  pendingRequests: number;
  processStatus: string;
}

export interface LSPStatusResult {
  configuredServers: LSPServerConfig[];
  runningInstances: LSPServerInstance[];
}

export interface LSPActionResult {
  success: boolean;
  action: string;
  key: string;
  server: string;
  workspace: string;
  processId?: string | null;
  error?: string | null;
}

export interface LSPDocumentSymbol {
  name: string;
  kind: number;
  kindName: string;
  filePath: string;
  lineStart: number;
  lineEnd: number;
  characterStart: number;
  characterEnd: number;
  detail?: string | null;
  children?: LSPDocumentSymbol[];
}

export interface LSPDocumentSymbolsResult {
  success: boolean;
  filePath: string;
  symbols?: LSPDocumentSymbol[];
  error?: string | null;
}

export interface KanbanTaskInfo {
  id: string;
  title: string;
  description: string;
  resolution: string;
  createdAt: string;
  updatedAt: string;
}

export interface ColumnInfo {
  id: string;
  name: string;
  position: number;
  taskIds?: string[];
}

export interface BoardInfo {
  id: string;
  name: string;
  defaultColumnId: string;
  createdAt: string;
}

export interface BoardStateInfo {
  board: BoardInfo;
  columns: ColumnInfo[];
  tasks: KanbanTaskInfo[];
}

export interface BoardSubscriptionResult {
  boardId: string;
  subscribed: boolean;
  board?: BoardStateInfo | null;
  error?: string | null;
}

export interface BoardUnsubscribeResult {
  boardId: string;
  unsubscribed: boolean;
  error?: string | null;
}

export interface TaskMovedEvent {
  boardId: string;
  taskId: string;
  fromColumnId: string;
  toColumnId: string;
  newPosition: number;
}

export interface TaskCreatedEvent {
  boardId: string;
  task: KanbanTaskInfo;
  columnId: string;
  position: number;
}

export interface TaskUpdatedEvent {
  boardId: string;
  task: KanbanTaskInfo;
}

export interface TaskDeletedEvent {
  boardId: string;
  taskId: string;
}

export interface TasksReorderedEvent {
  boardId: string;
  columnId: string;
  taskIds: string[];
}

export interface BoardCreatedEvent {
  board: BoardStateInfo;
}

export interface BoardDeletedEvent {
  boardId: string;
}

export interface ColumnAddedEvent {
  boardId: string;
  column: ColumnInfo;
}

export interface ColumnDeletedEvent {
  boardId: string;
  columnId: string;
  tasksMovedTo: string | null;
}

export interface BoardAssociationInfo {
  id: string;
  sessionId: string;
  boardId: string;
  role: string;
  createdAt: string;
  createdBy: string;
  inheritedFrom?: string | null;
}

export interface SessionBoardsResult {
  sessionId: string;
  associations: BoardAssociationInfo[];
  boards: BoardInfo[];
}

export interface BoardSessionsResult {
  boardId: string;
  associations: BoardAssociationInfo[];
}

export interface BoardAssociatedEvent {
  association: BoardAssociationInfo;
  board: BoardInfo;
}

export interface BoardDisassociatedEvent {
  sessionId: string;
  boardId: string;
  associationId: string;
}

