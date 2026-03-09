/**
 * SystemPromptView - Display system prompt components with token counts
 *
 * Shows the components that make up the system prompt:
 * - User base prompt (CLAUDE.md)
 * - Tool documentation
 * - Domain prompts (loaded domains)
 * - Session context (goals, bindings)
 *
 * Features:
 * - Real-time updates when domains load/unload via WebSocket events
 * - Expandable previews showing actual prompt content
 * - Per-section token counts with visual breakdown
 */

import React, { memo, useState, useCallback, useMemo, useEffect } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import type {
  PromptComponentInfo as ServerPromptComponentInfo,
  DomainInfoItem as ServerDomainInfoItem,
} from '../../../../generated/types';
import { createLogger } from '../../utils/debugLog';
import './SystemPromptView.css';

const debugLog = createLogger('SystemPromptView');

// Extended component info with full content
export interface PromptComponent {
  id: string;
  name: string;
  description: string;
  tokens: number;
  enabled: boolean;
  expandable: boolean;
  contentPreview?: string;
  fullContent?: string;
}

// Extended domain info with prompt content
export interface DomainInfo {
  id: string;
  name: string;
  loaded: boolean;
  promptTokens: number;
  contextTokens: number;
  tools: string[];
  promptContent?: string;
}

interface SystemPromptViewProps {
  sessionId: string | null;
  client?: BalloonsClient | null;
  isLoading?: boolean;
}

// Format token count as kt
function formatKt(tokens: number): string {
  if (tokens <= 0) return '0kt';
  const kt = Math.ceil(tokens / 100) / 10;
  if (kt < 1) return `.${Math.floor(kt * 10)}kt`;
  return `${kt.toFixed(1)}kt`;
}

// Format exact token count
function formatTokens(tokens: number): string {
  return tokens.toLocaleString();
}

// Chevron icon
function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`syspr-chevron ${open ? 'syspr-chevron--open' : ''}`}
    >
      <path d="M9 18l6-6-6-6" />
    </svg>
  );
}

// Token bar showing proportional usage
function TokenBar({ tokens, maxTokens }: { tokens: number; maxTokens: number }) {
  const pct = maxTokens > 0 ? Math.min(100, (tokens / maxTokens) * 100) : 0;
  return (
    <div className="syspr-token-bar">
      <div className="syspr-token-bar__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

// Prompt content preview with collapsible display
const PromptPreview = memo(function PromptPreview({
  content,
  maxLines = 10,
}: {
  content: string;
  maxLines?: number;
}) {
  const [isFullyExpanded, setIsFullyExpanded] = useState(false);
  const lines = content.split('\n');
  const needsTruncation = lines.length > maxLines;
  const displayContent = isFullyExpanded
    ? content
    : lines.slice(0, maxLines).join('\n') + (needsTruncation ? '\n...' : '');

  return (
    <div className="syspr-preview">
      <pre className="syspr-preview__content">{displayContent}</pre>
      {needsTruncation && (
        <button
          className="syspr-preview__toggle"
          onClick={() => setIsFullyExpanded(!isFullyExpanded)}
        >
          {isFullyExpanded ? 'Show less' : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
});

// Component row with expandable content preview
const ComponentRow = memo(function ComponentRow({
  component,
  expanded,
  onExpand,
  maxTokens,
}: {
  component: PromptComponent;
  expanded: boolean;
  onExpand: (id: string) => void;
  maxTokens: number;
}) {
  const hasContent = component.fullContent && component.fullContent.length > 0;
  const isExpandable = component.expandable || hasContent;

  const handleClick = useCallback(() => {
    if (isExpandable) {
      onExpand(component.id);
    }
  }, [component.id, isExpandable, onExpand]);

  return (
    <div className="syspr-component">
      <div
        className={`syspr-row ${isExpandable ? 'syspr-row--expandable' : ''}`}
        onClick={handleClick}
      >
        {/* Expand/collapse indicator */}
        <span className="syspr-row__expand">
          {isExpandable ? (
            <ChevronIcon open={expanded} />
          ) : (
            <span className="syspr-row__spacer" />
          )}
        </span>

        {/* Name and description */}
        <div className="syspr-row__content">
          <span className="syspr-row__name">{component.name}</span>
          <span className="syspr-row__desc">{component.description}</span>
        </div>

        {/* Token count with bar */}
        <div className="syspr-row__tokens-wrap">
          <span
            className={`syspr-row__tokens ${
              component.tokens > 0 ? 'syspr-row__tokens--active' : ''
            }`}
          >
            {formatKt(component.tokens)}
          </span>
          <TokenBar tokens={component.tokens} maxTokens={maxTokens} />
        </div>
      </div>

      {/* Expanded content preview */}
      {expanded && hasContent && (
        <div className="syspr-row__expanded">
          <div className="syspr-row__expanded-header">
            <span className="syspr-row__expanded-tokens">
              {formatTokens(component.tokens)} tokens
            </span>
          </div>
          <PromptPreview content={component.fullContent!} maxLines={15} />
        </div>
      )}
    </div>
  );
});

// Domain row with load/unload action and prompt preview
const DomainRow = memo(function DomainRow({
  domain,
  expanded,
  onExpand,
  onLoad,
  onUnload,
}: {
  domain: DomainInfo;
  expanded: boolean;
  onExpand: (id: string) => void;
  onLoad?: (id: string) => void;
  onUnload?: (id: string) => void;
}) {
  const totalTokens = domain.promptTokens + domain.contextTokens;
  const hasContent = domain.promptContent && domain.promptContent.length > 0;

  return (
    <div
      className={`syspr-domain ${domain.loaded ? 'syspr-domain--loaded' : ''}`}
    >
      <div
        className="syspr-domain__header"
        onClick={() => hasContent && onExpand(domain.id)}
      >
        {/* Expand indicator */}
        <span className="syspr-domain__expand">
          {hasContent ? (
            <ChevronIcon open={expanded} />
          ) : (
            <span className="syspr-row__spacer" />
          )}
        </span>

        <span className="syspr-domain__name">{domain.name}</span>
        <span className="syspr-domain__id">({domain.id})</span>

        {/* Load/Unload button */}
        {domain.loaded ? (
          <button
            className="syspr-domain__action syspr-domain__action--unload"
            onClick={(e) => {
              e.stopPropagation();
              onUnload?.(domain.id);
            }}
            title="Unload domain"
          >
            Unload
          </button>
        ) : (
          <button
            className="syspr-domain__action syspr-domain__action--load"
            onClick={(e) => {
              e.stopPropagation();
              onLoad?.(domain.id);
            }}
            title="Load domain"
          >
            Load
          </button>
        )}
        <span className="syspr-domain__tokens">{formatKt(totalTokens)}</span>
      </div>

      {/* Domain details (tools, token breakdown) */}
      {domain.loaded && (
        <div className="syspr-domain__details">
          <div className="syspr-domain__detail">
            <span className="syspr-domain__label">Prompt:</span>
            <span className="syspr-domain__value">
              {formatTokens(domain.promptTokens)} tokens
            </span>
          </div>
          {domain.contextTokens > 0 && (
            <div className="syspr-domain__detail">
              <span className="syspr-domain__label">Context:</span>
              <span className="syspr-domain__value">
                {formatTokens(domain.contextTokens)} tokens
              </span>
            </div>
          )}
          {domain.tools.length > 0 && (
            <div className="syspr-domain__detail">
              <span className="syspr-domain__label">Tools:</span>
              <span className="syspr-domain__value">{domain.tools.join(', ')}</span>
            </div>
          )}
        </div>
      )}

      {/* Expanded prompt preview */}
      {expanded && hasContent && (
        <div className="syspr-domain__expanded">
          <PromptPreview content={domain.promptContent!} maxLines={20} />
        </div>
      )}
    </div>
  );
});

export const SystemPromptView = memo(function SystemPromptView({
  sessionId,
  client,
  isLoading = false,
}: SystemPromptViewProps) {
  // DEBUG: Log every render
  console.log('[SystemPromptView] RENDER', { sessionId, hasClient: !!client, isLoading });

  // Components state
  const [components, setComponents] = useState<PromptComponent[]>([]);

  // Domains state
  const [domains, setDomains] = useState<DomainInfo[]>([]);

  // Context window from server
  const [contextWindow, setContextWindow] = useState(150000);

  // Expanded state for collapsible items
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Fetch system prompt info from server
  const fetchSystemPromptInfo = useCallback(async () => {
    console.log('[SystemPromptView] fetchSystemPromptInfo START', { hasClient: !!client, sessionId });
    debugLog('fetchSystemPromptInfo called', { hasClient: !!client, sessionId });
    if (!client) {
      console.log('[SystemPromptView] no client, returning early');
      debugLog('fetchSystemPromptInfo: no client, returning early');
      return;
    }

    try {
      console.log('[SystemPromptView] calling getSystemPromptInfo...');
      debugLog('Fetching system prompt info', { sessionId });
      const info = await client.sessions.getSystemPromptInfo(sessionId);
      console.log('[SystemPromptView] got result:', info);
      debugLog('Got system prompt info', {
        totalTokens: info.totalTokens,
        componentCount: info.components?.length,
        domainCount: info.domains?.length,
      });

      // Map server components to UI components
      if (info.components) {
        const mappedComponents: PromptComponent[] = info.components.map(
          (c: ServerPromptComponentInfo) => ({
            id: c.id,
            name: c.name,
            description: c.description,
            tokens: c.tokens ?? 0,
            enabled: c.enabled ?? true,
            expandable: Boolean(c.fullContent && c.fullContent.length > 0),
            contentPreview: c.contentPreview,
            fullContent: c.fullContent,
          })
        );
        setComponents(mappedComponents);
      }

      // Map server domains to UI domains
      if (info.domains) {
        const mappedDomains: DomainInfo[] = info.domains.map(
          (d: ServerDomainInfoItem) => ({
            id: d.id,
            name: d.name,
            loaded: d.loaded ?? false,
            promptTokens: d.promptTokens ?? 0,
            contextTokens: d.contextTokens ?? 0,
            tools: d.tools ?? [],
            promptContent: d.promptContent,
          })
        );
        setDomains(mappedDomains);
      }

      // Set context window
      if (info.contextWindow) {
        setContextWindow(info.contextWindow);
      }
    } catch (err) {
      console.error('[SystemPromptView] ERROR fetching:', err);
      debugLog('Error fetching system prompt info', { error: String(err) });
    }
  }, [client, sessionId]);

  // Initial fetch
  useEffect(() => {
    console.log('[SystemPromptView] useEffect triggered - calling fetchSystemPromptInfo');
    fetchSystemPromptInfo();
  }, [fetchSystemPromptInfo]);

  // Subscribe to domain load/unload events
  useEffect(() => {
    if (!client) return;

    // Subscribe to domain events
    const unsubscribeDomain = client.sessionData.sessionDataDomainEvent((event) => {
      // Check for system-level domain events
      if (event.domainId === 'system') {
        if (
          event.eventType === 'domain_loaded' ||
          event.eventType === 'domain_unloaded'
        ) {
          debugLog('Domain event received, refreshing', {
            eventType: event.eventType,
            data: event.data,
          });
          // Refresh the system prompt info when domains change
          fetchSystemPromptInfo();
        }
      }
    });

    // Subscribe to session update events (catches backend changes)
    const unsubscribeSession = client.sessionData.sessionDataSessionUpdated((event) => {
      // If this is our session, refresh to pick up any changes (like backend switch)
      if (event.sessionId === sessionId) {
        debugLog('Session updated, refreshing system prompt info', {
          sessionId: event.sessionId,
        });
        fetchSystemPromptInfo();
      }
    });

    return () => {
      unsubscribeDomain();
      unsubscribeSession();
    };
  }, [client, sessionId, fetchSystemPromptInfo]);

  // Handle expand/collapse
  const handleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  // Handle domain load
  const handleDomainLoad = useCallback(
    async (domainId: string) => {
      if (!client) return;
      debugLog('Load domain', { domainId });
      try {
        const result = await client.sessions.loadDomain(domainId);
        if (!result.success) {
          debugLog('Failed to load domain', { domainId, error: result.error });
        }
        // Note: Domain event will trigger refresh automatically
      } catch (err) {
        debugLog('Error loading domain', { domainId, error: String(err) });
      }
    },
    [client]
  );

  // Handle domain unload
  const handleDomainUnload = useCallback(
    async (domainId: string) => {
      if (!client) return;
      debugLog('Unload domain', { domainId });
      try {
        const result = await client.sessions.unloadDomain(domainId);
        if (!result.success) {
          debugLog('Failed to unload domain', { domainId, error: result.error });
        }
        // Note: Domain event will trigger refresh automatically
      } catch (err) {
        debugLog('Error unloading domain', { domainId, error: String(err) });
      }
    },
    [client]
  );

  // Calculate totals
  const totalTokens = useMemo(() => {
    const componentTokens = components
      .filter((c) => c.enabled)
      .reduce((sum, c) => sum + c.tokens, 0);
    const domainTokens = domains
      .filter((d) => d.loaded)
      .reduce((sum, d) => sum + d.promptTokens + d.contextTokens, 0);
    return componentTokens + domainTokens;
  }, [components, domains]);

  // Max tokens for proportional bars (use largest component)
  const maxTokens = useMemo(() => {
    const allTokens = [
      ...components.map((c) => c.tokens),
      ...domains.map((d) => d.promptTokens + d.contextTokens),
    ];
    return Math.max(...allTokens, 1);
  }, [components, domains]);

  // Find domains component for nested display
  const domainsComponent = components.find((c) => c.id === 'domains');
  const otherComponents = components.filter((c) => c.id !== 'domains');

  if (!sessionId) {
    return (
      <div className="syspr-view syspr-view--empty">
        <div className="syspr-view__empty-state">
          <h3>No Session Selected</h3>
          <p>Select a session to view its system prompt.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="syspr-view syspr-view--empty">
        <div className="syspr-view__empty-state">Loading system prompt info...</div>
      </div>
    );
  }

  // Show empty state if no components loaded
  if (components.length === 0 && domains.length === 0) {
    return (
      <div className="syspr-view syspr-view--empty">
        <div className="syspr-view__empty-state">
          <h3>No System Prompt Info</h3>
          <p>Unable to load system prompt components. Client: {client ? 'available' : 'not available'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="syspr-view">
      {/* Header */}
      <div className="syspr-view__header">
        <h3 className="syspr-view__title">System Prompt Components</h3>
        <span className="syspr-view__total">{formatKt(totalTokens)} total</span>
      </div>

      {/* Components list */}
      <div className="syspr-view__list">
        {otherComponents.map((component) => (
          <ComponentRow
            key={component.id}
            component={component}
            expanded={expandedIds.has(component.id)}
            onExpand={handleExpand}
            maxTokens={maxTokens}
          />
        ))}

        {/* Domains section */}
        {domainsComponent && (
          <div className="syspr-component syspr-component--domains">
            <div
              className="syspr-row syspr-row--expandable"
              onClick={() => handleExpand('domains')}
            >
              <span className="syspr-row__expand">
                <ChevronIcon open={expandedIds.has('domains')} />
              </span>
              <div className="syspr-row__content">
                <span className="syspr-row__name">{domainsComponent.name}</span>
                <span className="syspr-row__desc">
                  {domains.filter((d) => d.loaded).length} loaded,{' '}
                  {domains.length} available
                </span>
              </div>
              <div className="syspr-row__tokens-wrap">
                <span
                  className={`syspr-row__tokens ${
                    domainsComponent.tokens > 0 ? 'syspr-row__tokens--active' : ''
                  }`}
                >
                  {formatKt(domainsComponent.tokens)}
                </span>
              </div>
            </div>

            {/* Expanded domains list */}
            {expandedIds.has('domains') && (
              <div className="syspr-component__children">
                {domains.length === 0 ? (
                  <div className="syspr-domains-empty">No domains available</div>
                ) : (
                  domains.map((domain) => (
                    <DomainRow
                      key={domain.id}
                      domain={domain}
                      expanded={expandedIds.has(`domain-${domain.id}`)}
                      onExpand={(id) => handleExpand(`domain-${id}`)}
                      onLoad={handleDomainLoad}
                      onUnload={handleDomainUnload}
                    />
                  ))
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Footer with context usage */}
      <div className="syspr-view__footer">
        <div className="syspr-view__stat">
          <span className="syspr-view__stat-label">System Prompt:</span>
          <span className="syspr-view__stat-value">
            {formatTokens(totalTokens)} tokens ({formatKt(totalTokens)})
          </span>
        </div>
        <div className="syspr-view__stat">
          <span className="syspr-view__stat-label">Context Window:</span>
          <span className="syspr-view__stat-value">{formatKt(contextWindow)}</span>
        </div>
        <div className="syspr-view__usage">
          <span className="syspr-view__usage-label">Usage:</span>
          <div className="syspr-view__usage-bar">
            <div
              className="syspr-view__usage-fill"
              style={{
                width: `${Math.min(100, (totalTokens / contextWindow) * 100)}%`,
              }}
            />
          </div>
          <span className="syspr-view__usage-pct">
            {((totalTokens / contextWindow) * 100).toFixed(1)}%
          </span>
        </div>
      </div>
    </div>
  );
});

export default SystemPromptView;
