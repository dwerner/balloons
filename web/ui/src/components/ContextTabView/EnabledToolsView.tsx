/**
 * EnabledToolsView - Panel for managing which tools are enabled for a session
 *
 * Shows tools grouped by category with checkboxes to enable/disable each.
 * Changes are saved immediately to the session or global config.
 * Includes a Monaco editor showing the generated system prompt preview.
 *
 * Layout: Two columns - checkboxes on left, Monaco preview on right.
 */

import React, { useState, useEffect, useCallback, useMemo, memo } from 'react';
import Editor from '@monaco-editor/react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './EnabledToolsView.css';

const debugLog = createLogger('EnabledToolsView');

// Format char count as kt (thousands)
function formatLength(len: number): string {
  if (len < 1000) return `${len} chars`;
  const kt = Math.round(len / 100) / 10;
  return `${kt.toFixed(1)}k chars`;
}

interface AvailableTools {
  core: string[];
  categories: Record<string, string[]>;
  all: string[];
  domain_tools?: Record<string, string[]>;
}

interface EnabledToolsViewProps {
  sessionId: string | null;
  client: BalloonsClient | null;
  /** If true, edit global defaults instead of session-specific tools */
  isGlobalSettings?: boolean;
}

function formatCategoryLabel(category: string): string {
  if (!category) return 'Other';
  return category.charAt(0).toUpperCase() + category.slice(1);
}

// Tool descriptions for tooltips
const TOOL_DESCRIPTIONS: Record<string, string> = {
  // Core
  Read: 'Read file contents',
  Write: 'Write/create files',
  Edit: 'Edit files with find/replace',
  Bash: 'Execute shell commands',
  Glob: 'Find files by pattern',
  Grep: 'Search file contents',
  // Balloon
  ask_user: 'Ask user a question and wait for response',
  propose_fork: 'Propose creating a fork session',
  propose_merge: 'Propose merging back to parent',
  list_links: 'List linked sessions',
  follow_link: 'Load context from a linked session',
  search_linked_session: 'Search within a linked session',
  session_info: 'Get current session info',
  // Domain
  load_domain: 'Load a domain plugin (chess, kanban, etc.)',
  unload_domain: 'Unload a domain plugin',
  list_domains: 'List available domain plugins',
  // Supervisor
  supervisor_start: 'Start a background process',
  supervisor_list: 'List running processes',
  supervisor_output: 'Get process output',
  supervisor_stop: 'Stop a process',
  supervisor_query: 'Query available hosts',
  supervisor_host_status: 'Check host connectivity',
  // Watcher
  send_to_target: 'Send message to watched session',
  // MIDI
  play_midi: 'Play musical notes',
  // Debug
  debug_log_query: 'Query debug logs',
  debug_log_config: 'Configure debug logging',
  debug_log_tail: 'Tail log files',
};

export const EnabledToolsView = memo(function EnabledToolsView({
  sessionId,
  client,
  isGlobalSettings = false,
}: EnabledToolsViewProps) {
  const [availableTools, setAvailableTools] = useState<AvailableTools | null>(null);
  const [enabledTools, setEnabledTools] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Prompt preview state
  const [promptPreview, setPromptPreview] = useState<string>('');
  const [promptLength, setPromptLength] = useState<number>(0);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);

  // Tool schemas preview state (for OpenAI backends only)
  const [backendType, setBackendType] = useState<string>('claude');
  const [toolSchemasPreview, setToolSchemasPreview] = useState<string>('');
  const [toolSchemasLength, setToolSchemasLength] = useState<number>(0);
  const [isLoadingSchemasPreview, setIsLoadingSchemasPreview] = useState(false);
  const [previewTab, setPreviewTab] = useState<'prompt' | 'schemas'>('prompt');

  // Domain plugin state
  const [loadedDomains, setLoadedDomains] = useState<string[]>([]);
  const [availableDomains, setAvailableDomains] = useState<string[]>([]);

  // Mobile view state (tabs instead of side-by-side)
  const [mobileTab, setMobileTab] = useState<'tools' | 'preview'>('tools');
  const [isMobile, setIsMobile] = useState(false);

  // Detect mobile viewport
  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth <= 768);
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  // Dark mode detection
  const [isDarkMode, setIsDarkMode] = useState(true);
  useEffect(() => {
    const checkDarkMode = () => {
      const theme = document.documentElement.getAttribute('data-theme');
      setIsDarkMode(theme !== 'light');
    };
    checkDarkMode();
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => observer.disconnect();
  }, []);

  // Load available tools and current enabled state
  useEffect(() => {
    if (!client) return;

    const loadData = async () => {
      setIsLoading(true);
      setError(null);
      try {
        // Load available tools
        const available = await client.sessions.getAvailableTools() as unknown as AvailableTools;
        setAvailableTools(available);
        debugLog('Loaded available tools', available);

        // Load current enabled tools
        let enabled: string[];
        if (isGlobalSettings) {
          enabled = await client.sessions.getDefaultEnabledTools();
          debugLog('Loaded global default enabled tools', enabled);
        } else if (sessionId) {
          enabled = await client.sessions.getSessionEnabledTools(sessionId);
          debugLog('Loaded session enabled tools', { sessionId, enabled });
        } else {
          enabled = available.all;
        }
        setEnabledTools(new Set(enabled));

        // Load domain info
        try {
          const domainInfo = await client.sessions.getDomainInfo() as { available: string[]; loaded: string[] };
          setAvailableDomains(domainInfo.available);
          setLoadedDomains(domainInfo.loaded);
          debugLog('Loaded domain info', domainInfo);
        } catch {
          // Domain system might not be available
          setAvailableDomains([]);
          setLoadedDomains([]);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setError(msg);
        debugLog('Error loading tools', { error: msg });
      } finally {
        setIsLoading(false);
      }
    };

    loadData();
  }, [client, sessionId, isGlobalSettings]);

  // Toggle a tool
  const handleToggleTool = useCallback(async (toolName: string) => {
    if (!client || isSaving) return;

    const newEnabled = new Set(enabledTools);
    if (newEnabled.has(toolName)) {
      newEnabled.delete(toolName);
    } else {
      newEnabled.add(toolName);
    }

    // Optimistic update
    setEnabledTools(newEnabled);

    // Save
    setIsSaving(true);
    try {
      const toolList = Array.from(newEnabled);
      if (isGlobalSettings) {
        await client.sessions.setDefaultEnabledTools(toolList);
        debugLog('Saved global default enabled tools', toolList);
      } else if (sessionId) {
        await client.sessions.setSessionEnabledTools(sessionId, toolList);
        debugLog('Saved session enabled tools', { sessionId, toolList });
      }
    } catch (e) {
      // Revert on error
      setEnabledTools(enabledTools);
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      debugLog('Error saving tools', { error: msg });
    } finally {
      setIsSaving(false);
    }
  }, [client, sessionId, isGlobalSettings, enabledTools, isSaving]);

  // Toggle all tools in a category
  const handleToggleCategory = useCallback(async (category: string, tools: string[]) => {
    if (!client || isSaving) return;

    // Check if all are currently enabled
    const allEnabled = tools.every(t => enabledTools.has(t));

    const newEnabled = new Set(enabledTools);
    if (allEnabled) {
      // Disable all
      tools.forEach(t => newEnabled.delete(t));
    } else {
      // Enable all
      tools.forEach(t => newEnabled.add(t));
    }

    // Optimistic update
    setEnabledTools(newEnabled);

    // Save
    setIsSaving(true);
    try {
      const toolList = Array.from(newEnabled);
      if (isGlobalSettings) {
        await client.sessions.setDefaultEnabledTools(toolList);
      } else if (sessionId) {
        await client.sessions.setSessionEnabledTools(sessionId, toolList);
      }
    } catch (e) {
      setEnabledTools(enabledTools);
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setIsSaving(false);
    }
  }, [client, sessionId, isGlobalSettings, enabledTools, isSaving]);

  // Reset to defaults
  const handleResetToDefaults = useCallback(async () => {
    if (!client || isSaving || isGlobalSettings) return;

    setIsSaving(true);
    try {
      const defaults = await client.sessions.getDefaultEnabledTools();
      await client.sessions.setSessionEnabledTools(sessionId!, defaults);
      setEnabledTools(new Set(defaults));
      debugLog('Reset to defaults', defaults);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
    } finally {
      setIsSaving(false);
    }
  }, [client, sessionId, isGlobalSettings, isSaving]);

  // Load prompt preview
  const loadPromptPreview = useCallback(async () => {
    if (!client) return;

    setIsLoadingPreview(true);
    try {
      const result = await client.sessions.getPromptPreview(
        sessionId || undefined,
        Array.from(enabledTools)
      ) as { prompt: string; length: number };
      setPromptPreview(result.prompt);
      setPromptLength(result.length);
      debugLog('Loaded prompt preview', { length: result.length });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      debugLog('Error loading prompt preview', { error: msg });
      setPromptPreview(`Error loading preview: ${msg}`);
      setPromptLength(0);
    } finally {
      setIsLoadingPreview(false);
    }
  }, [client, sessionId, enabledTools]);

  // Load tool schemas preview (for OpenAI backends)
  const loadToolSchemasPreview = useCallback(async () => {
    if (!client) return;

    setIsLoadingSchemasPreview(true);
    try {
      const result = await client.sessions.getToolSchemasPreview(
        sessionId || undefined,
        Array.from(enabledTools)
      ) as { schemas: string; tool_count: number; length: number };
      setToolSchemasPreview(result.schemas);
      setToolSchemasLength(result.length);
      debugLog('Loaded tool schemas preview', { length: result.length, count: result.tool_count });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      debugLog('Error loading tool schemas preview', { error: msg });
      setToolSchemasPreview(`Error loading schemas: ${msg}`);
      setToolSchemasLength(0);
    } finally {
      setIsLoadingSchemasPreview(false);
    }
  }, [client, sessionId, enabledTools]);

  // Load backend type from session info
  const loadBackendType = useCallback(async () => {
    if (!client) return;

    try {
      const result = await client.sessions.getSystemPromptInfo(sessionId || undefined);
      const type = result.backendType || 'claude';
      setBackendType(type);
      debugLog('Loaded backend type', { backendType: type });
    } catch (e) {
      debugLog('Error loading backend type', { error: e });
      setBackendType('claude'); // Default to claude
    }
  }, [client, sessionId]);

  // Refresh domain info from backend
  const refreshDomainInfo = useCallback(async () => {
    if (!client) return;
    try {
      const domainInfo = await client.sessions.getDomainInfo() as { available: string[]; loaded: string[] };
      setAvailableDomains(domainInfo.available);
      setLoadedDomains(domainInfo.loaded);
      debugLog('Refreshed domain info', domainInfo);
    } catch {
      // Domain system might not be available
    }
  }, [client]);

  // Load/unload a domain (persists to session if sessionId provided)
  const handleToggleDomain = useCallback(async (domainId: string, isLoaded: boolean) => {
    if (!client || isSaving) return;

    setIsSaving(true);
    try {
      if (isLoaded) {
        // Pass sessionId to persist the change
        await client.sessions.unloadDomain(domainId, sessionId || undefined);
        debugLog('Unloaded domain', { domainId, sessionId });
      } else {
        // Pass sessionId to persist the change
        await client.sessions.loadDomain(domainId, sessionId || undefined);
        debugLog('Loaded domain', { domainId, sessionId });
      }
      // Refresh domain info from backend to get actual state
      await refreshDomainInfo();
      // Refresh preview after domain change
      setTimeout(loadPromptPreview, 100);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      debugLog('Error toggling domain', { domainId, error: msg });
    } finally {
      setIsSaving(false);
    }
  }, [client, sessionId, isSaving, loadPromptPreview, refreshDomainInfo]);

  // Load backend type on mount
  useEffect(() => {
    loadBackendType();
  }, [loadBackendType]);

  // Load previews when tools change
  useEffect(() => {
    if (!isLoading) {
      loadPromptPreview();
      // Also load schemas for OpenAI backends
      if (backendType === 'openai') {
        loadToolSchemasPreview();
      }
    }
  }, [isLoading, loadPromptPreview, loadToolSchemasPreview, backendType]);

  // Subscribe to domain loaded/unloaded events to stay in sync with DomainsTab
  useEffect(() => {
    if (!client) return;

    const unsubscribe = client.sessionData.sessionDataDomainEvent((event) => {
      // System-level domain events (load/unload)
      if (event.domainId === 'system') {
        const data = event.data as { domainId?: string };
        const domainId = data.domainId;

        if (!domainId) return;

        if (event.eventType === 'domain_loaded') {
          debugLog('Domain loaded event received', { domainId });
          setLoadedDomains(prev => prev.includes(domainId) ? prev : [...prev, domainId]);
          // Refresh previews when domains change
          loadPromptPreview();
          if (backendType === 'openai') {
            loadToolSchemasPreview();
          }
        } else if (event.eventType === 'domain_unloaded') {
          debugLog('Domain unloaded event received', { domainId });
          setLoadedDomains(prev => prev.filter(d => d !== domainId));
          // Refresh previews when domains change
          loadPromptPreview();
          if (backendType === 'openai') {
            loadToolSchemasPreview();
          }
        }
      }
    });

    return unsubscribe;
  }, [client, loadPromptPreview, loadToolSchemasPreview, backendType]);

  // Build category groups
  const categoryGroups = useMemo(() => {
    if (!availableTools) return [];

    const groups: Array<{ key: string; label: string; tools: string[] }> = [];
    const domainPluginTools = new Set(
      Object.values(availableTools.domain_tools || {}).flat()
    );

    if (availableTools.core.length > 0) {
      groups.push({
        key: 'core',
        label: 'Core',
        tools: [...availableTools.core].sort((a, b) => a.localeCompare(b)),
      });
    }

    const discoveredCategories = Object.entries(availableTools.categories)
      .filter(([category, tools]) => category !== 'domain_plugins' && tools && tools.length > 0)
      .sort(([a], [b]) => a.localeCompare(b));

    for (const [category, tools] of discoveredCategories) {
      groups.push({
        key: category,
        label: formatCategoryLabel(category),
        tools: [...tools].filter(tool => !domainPluginTools.has(tool)).sort((a, b) => a.localeCompare(b)),
      });
    }

    if (domainPluginTools.size > 0) {
      groups.push({
        key: 'domain_plugins',
        label: 'Domain Plugin Tools',
        tools: [...domainPluginTools].sort((a, b) => a.localeCompare(b)),
      });
    }

    return groups.filter(group => group.tools.length > 0);
  }, [availableTools]);

  if (isLoading) {
    return (
      <div className="enabled-tools-view">
        <div className="enabled-tools-view__loading">Loading tools...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="enabled-tools-view">
        <div className="enabled-tools-view__error">{error}</div>
      </div>
    );
  }

  if (!availableTools) {
    return (
      <div className="enabled-tools-view">
        <div className="enabled-tools-view__empty">No tools available</div>
      </div>
    );
  }

  // Render the tools panel content
  const renderToolsPanel = () => (
    <>
      <div className="enabled-tools-view__header">
        <h3 className="enabled-tools-view__title">
          {isGlobalSettings ? 'Default Enabled Tools' : 'Session Tools'}
        </h3>
        <div className="enabled-tools-view__actions">
          <span className="enabled-tools-view__count">
            {enabledTools.size}/{availableTools.all.length}
          </span>
          {!isGlobalSettings && sessionId && (
            <button
              className="enabled-tools-view__reset-btn"
              onClick={handleResetToDefaults}
              disabled={isSaving}
              title="Reset to default enabled tools"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      <div className="enabled-tools-view__categories">
        {categoryGroups.map(group => {
          const allEnabled = group.tools.every(t => enabledTools.has(t));
          const someEnabled = group.tools.some(t => enabledTools.has(t));
          const enabledCount = group.tools.filter(t => enabledTools.has(t)).length;

          return (
            <div key={group.key} className="enabled-tools-view__category">
              <div
                className="enabled-tools-view__category-header"
                onClick={() => handleToggleCategory(group.key, group.tools)}
              >
                <input
                  type="checkbox"
                  checked={allEnabled}
                  ref={el => {
                    if (el) el.indeterminate = someEnabled && !allEnabled;
                  }}
                  onChange={() => handleToggleCategory(group.key, group.tools)}
                  onClick={e => e.stopPropagation()}
                  disabled={isSaving}
                />
                <span className="enabled-tools-view__category-label">{group.label}</span>
                <span className="enabled-tools-view__category-count">
                  {enabledCount}/{group.tools.length}
                </span>
              </div>

              <div className="enabled-tools-view__tools">
                {group.tools.map(tool => (
                  <label
                    key={tool}
                    className={`enabled-tools-view__tool ${enabledTools.has(tool) ? 'enabled-tools-view__tool--enabled' : ''}`}
                    title={TOOL_DESCRIPTIONS[tool] || tool}
                  >
                    <input
                      type="checkbox"
                      checked={enabledTools.has(tool)}
                      onChange={() => handleToggleTool(tool)}
                      disabled={isSaving}
                    />
                    <span className="enabled-tools-view__tool-name">{tool}</span>
                  </label>
                ))}
              </div>
            </div>
          );
        })}

        {/* Loaded Domains Section */}
        {availableDomains.length > 0 && (
          <div className="enabled-tools-view__category enabled-tools-view__category--domains">
            <div className="enabled-tools-view__category-header enabled-tools-view__category-header--domains">
              <span className="enabled-tools-view__category-icon">🔌</span>
              <span className="enabled-tools-view__category-label">Domain Plugins</span>
              <span className="enabled-tools-view__category-count">
                {loadedDomains.length}/{availableDomains.length}
              </span>
            </div>
            <div className="enabled-tools-view__tools">
              {availableDomains.map(domain => {
                const isLoaded = loadedDomains.includes(domain);
                return (
                  <label
                    key={domain}
                    className={`enabled-tools-view__tool ${isLoaded ? 'enabled-tools-view__tool--enabled' : ''}`}
                    title={`${isLoaded ? 'Unload' : 'Load'} ${domain} domain`}
                  >
                    <input
                      type="checkbox"
                      checked={isLoaded}
                      onChange={() => handleToggleDomain(domain, isLoaded)}
                      disabled={isSaving}
                    />
                    <span className="enabled-tools-view__tool-name">{domain}</span>
                    {isLoaded && <span className="enabled-tools-view__domain-badge">loaded</span>}
                  </label>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {isSaving && (
        <div className="enabled-tools-view__saving">Saving...</div>
      )}
    </>
  );

  // Render the preview panel content
  const renderPreviewPanel = () => {
    const isOpenAI = backendType === 'openai';
    const showingPrompt = previewTab === 'prompt';
    const currentPreview = showingPrompt ? promptPreview : toolSchemasPreview;
    const currentLength = showingPrompt ? promptLength : toolSchemasLength;
    const currentLoading = showingPrompt ? isLoadingPreview : isLoadingSchemasPreview;
    const language = showingPrompt ? 'markdown' : 'json';

    return (
      <>
        <div className="enabled-tools-view__preview-header">
          {isOpenAI ? (
            // OpenAI: Show tabs to switch between prompt and schemas
            <div className="enabled-tools-view__preview-tabs">
              <button
                className={`enabled-tools-view__preview-tab ${showingPrompt ? 'enabled-tools-view__preview-tab--active' : ''}`}
                onClick={() => setPreviewTab('prompt')}
              >
                System Prompt
              </button>
              <button
                className={`enabled-tools-view__preview-tab ${!showingPrompt ? 'enabled-tools-view__preview-tab--active' : ''}`}
                onClick={() => {
                  setPreviewTab('schemas');
                  // Load schemas on first click if not loaded
                  if (toolSchemasPreview === '') {
                    loadToolSchemasPreview();
                  }
                }}
              >
                Tool Schemas
              </button>
            </div>
          ) : (
            // Claude: Just show title
            <span className="enabled-tools-view__preview-title">System Prompt</span>
          )}
          <span className="enabled-tools-view__preview-length">
            {currentLoading ? 'Loading...' : formatLength(currentLength)}
          </span>
        </div>
        <div className="enabled-tools-view__preview-editor">
          {currentLoading ? (
            <div className="enabled-tools-view__preview-loading">
              Loading {showingPrompt ? 'prompt' : 'schemas'} preview...
            </div>
          ) : (
            <Editor
              height="100%"
              language={language}
              value={currentPreview}
              theme={isDarkMode ? 'vs-dark' : 'light'}
              options={{
                readOnly: true,
                minimap: { enabled: false },
                fontSize: 12,
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                padding: { top: 8, bottom: 8 },
                folding: true,
                foldingStrategy: 'indentation',
              }}
            />
          )}
        </div>
      </>
    );
  };

  // Mobile: tab-based layout
  if (isMobile) {
    return (
      <div className="enabled-tools-view enabled-tools-view--mobile">
        {/* Tab bar */}
        <div className="enabled-tools-view__tabs">
          <button
            className={`enabled-tools-view__tab ${mobileTab === 'tools' ? 'enabled-tools-view__tab--active' : ''}`}
            onClick={() => setMobileTab('tools')}
          >
            Tools ({enabledTools.size})
          </button>
          <button
            className={`enabled-tools-view__tab ${mobileTab === 'preview' ? 'enabled-tools-view__tab--active' : ''}`}
            onClick={() => setMobileTab('preview')}
          >
            Preview ({formatLength(promptLength)})
          </button>
        </div>

        {/* Tab content */}
        <div className="enabled-tools-view__tab-content">
          {mobileTab === 'tools' ? (
            <div className="enabled-tools-view__sidebar enabled-tools-view__sidebar--mobile">
              {renderToolsPanel()}
            </div>
          ) : (
            <div className="enabled-tools-view__preview enabled-tools-view__preview--mobile">
              {renderPreviewPanel()}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Desktop: side-by-side layout
  return (
    <div className="enabled-tools-view enabled-tools-view--split">
      {/* Left column: checkboxes */}
      <div className="enabled-tools-view__sidebar">
        {renderToolsPanel()}
      </div>

      {/* Right column: Monaco preview */}
      <div className="enabled-tools-view__preview">
        {renderPreviewPanel()}
      </div>
    </div>
  );
});
