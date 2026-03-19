/**
 * Type definitions for the Calendar plugin
 */

export interface RecurrenceRule {
  frequency: 'daily' | 'weekly' | 'monthly' | 'yearly';
  interval: number;
  count?: number;
  until?: string;
  byDay?: string[];
  byMonthDay?: number;
}

export interface CalendarEvent {
  id: string;
  title: string;
  description: string;
  start: string; // ISO datetime
  end: string; // ISO datetime
  allDay: boolean;
  location?: string;
  color?: string;
  recurrence?: RecurrenceRule;
  source: 'local' | 'ical' | 'google';
  sourceId?: string;
  sourceUrl?: string;
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
}

export interface SyncStatus {
  state: 'idle' | 'syncing' | 'synced' | 'error';
  lastSynced?: string;
  error?: string;
}

export interface Calendar {
  id: string;
  name: string;
  color: string;
  provider: 'local' | 'ical' | 'google';
  providerConfig: Record<string, unknown>;
  events: CalendarEvent[];
  syncStatus: SyncStatus;
  createdAt: string;
  updatedAt: string;
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

// View mode for the calendar
export type ViewMode = 'month' | 'gantt';

// Date range for views
export interface DateRange {
  start: Date;
  end: Date;
}
