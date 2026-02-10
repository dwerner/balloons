// AUTO-GENERATED CODE - DO NOT EDIT
//
// Generated from Python @ws_expose and @ws_type decorators.
// Generated: 2026-02-10T07:52:59.260331
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
  bindingIndicator?: string;
}

export interface TurnInfo {
  idx: number;
  role: string;
  content: string;
  streaming: boolean;
  viewed: boolean;
  tokens: number;
  contextMode: string;
  exchangeId?: string | null;
}

export interface TreeEventData {
  eventType: string;
  sessionId: string;
  turnIdx?: number | null;
  data?: Record<string, unknown>;
}

