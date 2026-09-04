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

import React, { memo, useState, useCallback, useMemo, useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import type {
  PromptComponentInfo as ServerPromptComponentInfo,
  DomainInfoItem as ServerDomainInfoItem,
  SessionPromptFileInfo as ServerSessionPromptFileInfo,
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

// Session prompt file info
export interface SessionPromptFile {
  filePath: string;
  filename: string;
  tokens: number;
  exists: boolean;
  contentPreview?: string;
  fullContent?: string;
}

interface SystemPromptViewProps {
  sessionId: string | null;
  client?: BalloonsClient | null;
  isLoading?: boolean;
  /** Whether dark mode is enabled */
  isDarkMode?: boolean;
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

// Session prompt file row with remove action, content preview, and edit capability
const SessionPromptFileRow = memo(function SessionPromptFileRow({
  file,
  expanded,
  onExpand,
  onRemove,
  onSave,
  isDarkMode = true,
}: {
  file: SessionPromptFile;
  expanded: boolean;
  onExpand: (filePath: string) => void;
  onRemove?: (filePath: string) => void;
  onSave?: (filePath: string, content: string) => Promise<boolean>;
  isDarkMode?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(file.fullContent || '');
  const [isSaving, setIsSaving] = useState(false);
  const hasContent = file.fullContent && file.fullContent.length > 0;

  // Sync edit content when file content changes (e.g., after refresh)
  useEffect(() => {
    if (!isEditing) {
      setEditContent(file.fullContent || '');
    }
  }, [file.fullContent, isEditing]);

  const handleEdit = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsEditing(true);
    setEditContent(file.fullContent || '');
    // Expand if not already expanded
    if (!expanded) {
      onExpand(file.filePath);
    }
  }, [file.fullContent, file.filePath, expanded, onExpand]);

  const handleSave = useCallback(async () => {
    if (!onSave) return;
    setIsSaving(true);
    try {
      const success = await onSave(file.filePath, editContent);
      if (success) {
        setIsEditing(false);
      }
    } finally {
      setIsSaving(false);
    }
  }, [file.filePath, editContent, onSave]);

  const handleCancel = useCallback(() => {
    setIsEditing(false);
    setEditContent(file.fullContent || '');
  }, [file.fullContent]);

  const handleEditorChange = useCallback((value: string | undefined) => {
    setEditContent(value || '');
  }, []);

  // Detect language from filename
  const getLanguage = (filename: string): string => {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    const languageMap: Record<string, string> = {
      'md': 'markdown',
      'txt': 'plaintext',
      'json': 'json',
      'yaml': 'yaml',
      'yml': 'yaml',
      'toml': 'toml',
      'py': 'python',
      'js': 'javascript',
      'ts': 'typescript',
      'tsx': 'typescript',
      'jsx': 'javascript',
    };
    return languageMap[ext] || 'plaintext';
  };

  return (
    <div
      className={`syspr-prompt-file ${!file.exists ? 'syspr-prompt-file--missing' : ''} ${isEditing ? 'syspr-prompt-file--editing' : ''}`}
    >
      <div
        className="syspr-prompt-file__header"
        onClick={() => hasContent && onExpand(file.filePath)}
      >
        {/* Expand indicator */}
        <span className="syspr-prompt-file__expand">
          {hasContent ? (
            <ChevronIcon open={expanded} />
          ) : (
            <span className="syspr-row__spacer" />
          )}
        </span>

        <span className="syspr-prompt-file__name">{file.filename}</span>
        {!file.exists && (
          <span className="syspr-prompt-file__warning" title="File not found">⚠</span>
        )}

        {/* Edit button */}
        {file.exists && !isEditing && onSave && (
          <button
            className="syspr-prompt-file__action syspr-prompt-file__action--edit"
            onClick={handleEdit}
            title="Edit file"
          >
            ✎
          </button>
        )}

        {/* Remove button */}
        <button
          className="syspr-prompt-file__action syspr-prompt-file__action--remove"
          onClick={(e) => {
            e.stopPropagation();
            onRemove?.(file.filePath);
          }}
          title="Remove from session prompts"
        >
          ✕
        </button>
        <span className="syspr-prompt-file__tokens">{formatKt(file.tokens)}</span>
      </div>

      {/* File path tooltip */}
      <div className="syspr-prompt-file__path" title={file.filePath}>
        {file.filePath}
      </div>

      {/* Editor mode */}
      {expanded && isEditing && (
        <div className="syspr-prompt-file__editor">
          <div className="syspr-prompt-file__editor-toolbar">
            <button
              className="syspr-prompt-file__editor-btn syspr-prompt-file__editor-btn--save"
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : 'Save'}
            </button>
            <button
              className="syspr-prompt-file__editor-btn syspr-prompt-file__editor-btn--cancel"
              onClick={handleCancel}
              disabled={isSaving}
            >
              Cancel
            </button>
          </div>
          <div className="syspr-prompt-file__editor-container">
            <Editor
              height="300px"
              language={getLanguage(file.filename)}
              value={editContent}
              theme={isDarkMode ? 'vs-dark' : 'light'}
              onChange={handleEditorChange}
              options={{
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                padding: { top: 8, bottom: 8 },
              }}
            />
          </div>
        </div>
      )}

      {/* Preview mode (non-editing) */}
      {expanded && !isEditing && hasContent && (
        <div className="syspr-prompt-file__expanded">
          <PromptPreview content={file.fullContent!} maxLines={20} />
        </div>
      )}
    </div>
  );
});

export const SystemPromptView = memo(function SystemPromptView({
  sessionId,
  client,
  isLoading = false,
  isDarkMode: isDarkModeProp,
}: SystemPromptViewProps) {
  // DEBUG: Log every render
  debugLog('RENDER', { sessionId, hasClient: !!client, isLoading });

  // Detect dark mode from document attribute or prop
  const [detectedDarkMode, setDetectedDarkMode] = useState(true);
  useEffect(() => {
    const checkDarkMode = () => {
      const theme = document.documentElement.getAttribute('data-theme');
      setDetectedDarkMode(theme !== 'light');
    };
    checkDarkMode();
    // Watch for theme changes
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);
  const isDarkMode = isDarkModeProp ?? detectedDarkMode;

  // Components state
  const [components, setComponents] = useState<PromptComponent[]>([]);

  // Domains state
  const [domains, setDomains] = useState<DomainInfo[]>([]);

  // Session prompt files state
  const [sessionPromptFiles, setSessionPromptFiles] = useState<SessionPromptFile[]>([]);

  // Context window from server
  const [contextWindow, setContextWindow] = useState(150000);

  // Expanded state for collapsible items
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  // Fetch system prompt info from server
  const fetchSystemPromptInfo = useCallback(async () => {
    debugLog('fetchSystemPromptInfo START', { hasClient: !!client, sessionId });
    debugLog('fetchSystemPromptInfo called', { hasClient: !!client, sessionId });
    if (!client) {
      debugLog('no client, returning early');
      debugLog('fetchSystemPromptInfo: no client, returning early');
      return;
    }

    try {
      debugLog('calling getSystemPromptInfo...');
      debugLog('Fetching system prompt info', { sessionId });
      const info = await client.sessions.getSystemPromptInfo(sessionId);
      debugLog('got result:', info);
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

      // Map server session prompt files to UI format
      if (info.sessionPromptFiles) {
        const mappedFiles: SessionPromptFile[] = info.sessionPromptFiles.map(
          (f: ServerSessionPromptFileInfo) => ({
            filePath: f.filePath,
            filename: f.filename,
            tokens: f.tokens ?? 0,
            exists: f.exists ?? true,
            contentPreview: f.contentPreview,
            fullContent: f.fullContent,
          })
        );
        setSessionPromptFiles(mappedFiles);
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
    debugLog('useEffect triggered - calling fetchSystemPromptInfo');
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

  // Handle removing a session prompt file
  const handleRemovePromptFile = useCallback(
    async (filePath: string) => {
      if (!client || !sessionId) return;
      debugLog('Remove session prompt file', { filePath, sessionId });
      try {
        const result = await client.sessions.removeSessionPromptFile(sessionId, filePath);
        if (!result.success) {
          debugLog('Failed to remove prompt file', { filePath, error: result.error });
        }
        // Session update event will trigger refresh
      } catch (err) {
        debugLog('Error removing prompt file', { filePath, error: String(err) });
      }
    },
    [client, sessionId]
  );

  // Handle saving a session prompt file
  const handleSavePromptFile = useCallback(
    async (filePath: string, content: string): Promise<boolean> => {
      if (!client) return false;
      debugLog('Save session prompt file', { filePath, contentLength: content.length });
      try {
        const result = await client.files.writeFile(filePath, content);
        if (result.success) {
          debugLog('Saved prompt file successfully', { filePath });
          // Refresh to update token counts
          fetchSystemPromptInfo();
          return true;
        } else {
          debugLog('Failed to save prompt file', { filePath, error: result.message });
          return false;
        }
      } catch (err) {
        debugLog('Error saving prompt file', { filePath, error: String(err) });
        return false;
      }
    },
    [client, fetchSystemPromptInfo]
  );

  // Calculate totals
  const totalTokens = useMemo(() => {
    const componentTokens = components
      .filter((c) => c.enabled)
      .reduce((sum, c) => sum + c.tokens, 0);
    const domainTokens = domains
      .filter((d) => d.loaded)
      .reduce((sum, d) => sum + d.promptTokens + d.contextTokens, 0);
    // Session prompt files are already included in components via 'session-prompts'
    return componentTokens + domainTokens;
  }, [components, domains]);

  // Max tokens for proportional bars (use largest component)
  const maxTokens = useMemo(() => {
    const allTokens = [
      ...components.map((c) => c.tokens),
      ...domains.map((d) => d.promptTokens + d.contextTokens),
      ...sessionPromptFiles.map((f) => f.tokens),
    ];
    return Math.max(...allTokens, 1);
  }, [components, domains, sessionPromptFiles]);

  // Find domains component and session-prompts component for nested display
  const domainsComponent = components.find((c) => c.id === 'domains');
  const sessionPromptsComponent = components.find((c) => c.id === 'session-prompts');
  const otherComponents = components.filter((c) => c.id !== 'domains' && c.id !== 'session-prompts');

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

        {/* Session Prompts section */}
        {sessionPromptsComponent && (
          <div className="syspr-component syspr-component--session-prompts">
            <div
              className="syspr-row syspr-row--expandable"
              onClick={() => handleExpand('session-prompts')}
            >
              <span className="syspr-row__expand">
                <ChevronIcon open={expandedIds.has('session-prompts')} />
              </span>
              <div className="syspr-row__content">
                <span className="syspr-row__name">{sessionPromptsComponent.name}</span>
                <span className="syspr-row__desc">
                  {sessionPromptFiles.length} file{sessionPromptFiles.length !== 1 ? 's' : ''}
                </span>
              </div>
              <div className="syspr-row__tokens-wrap">
                <span
                  className={`syspr-row__tokens ${
                    sessionPromptsComponent.tokens > 0 ? 'syspr-row__tokens--active' : ''
                  }`}
                >
                  {formatKt(sessionPromptsComponent.tokens)}
                </span>
              </div>
            </div>

            {/* Expanded session prompt files list */}
            {expandedIds.has('session-prompts') && (
              <div className="syspr-component__children">
                {sessionPromptFiles.length === 0 ? (
                  <div className="syspr-prompt-files-empty">
                    No files added. Use the file browser context menu to add files as prompts.
                  </div>
                ) : (
                  sessionPromptFiles.map((file) => (
                    <SessionPromptFileRow
                      key={file.filePath}
                      file={file}
                      expanded={expandedIds.has(`file-${file.filePath}`)}
                      onExpand={(path) => handleExpand(`file-${path}`)}
                      onRemove={handleRemovePromptFile}
                      onSave={handleSavePromptFile}
                      isDarkMode={isDarkMode}
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
