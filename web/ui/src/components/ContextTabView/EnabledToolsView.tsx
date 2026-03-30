/**
 * EnabledToolsView - Panel for managing which tools are enabled for a session
 *
 * Shows tools grouped by category with checkboxes to enable/disable each.
 * Changes are saved immediately to the session or global config.
 */

import React, { useState, useEffect, useCallback, useMemo, memo } from 'react';
import type { BalloonsClient } from '../../../../generated/balloons-client';
import { createLogger } from '../../utils/debugLog';
import './EnabledToolsView.css';

const debugLog = createLogger('EnabledToolsView');

interface AvailableTools {
  core: string[];
  categories: Record<string, string[]>;
  all: string[];
}

interface EnabledToolsViewProps {
  sessionId: string | null;
  client: BalloonsClient | null;
  /** If true, edit global defaults instead of session-specific tools */
  isGlobalSettings?: boolean;
}

// Category display names and order
const CATEGORY_LABELS: Record<string, string> = {
  core: 'Core',
  balloon: 'Balloon',
  supervisor: 'Supervisor',
  watcher: 'Watcher',
  midi: 'MIDI',
  debug: 'Debug',
};

const CATEGORY_ORDER = ['core', 'balloon', 'supervisor', 'watcher', 'midi', 'debug'];

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

  // Build category groups
  const categoryGroups = useMemo(() => {
    if (!availableTools) return [];

    const groups: Array<{ key: string; label: string; tools: string[] }> = [];

    // Add core tools first
    if (availableTools.core.length > 0) {
      groups.push({
        key: 'core',
        label: CATEGORY_LABELS.core || 'Core',
        tools: availableTools.core,
      });
    }

    // Add other categories in order
    for (const cat of CATEGORY_ORDER) {
      if (cat === 'core') continue;
      const tools = availableTools.categories[cat];
      if (tools && tools.length > 0) {
        groups.push({
          key: cat,
          label: CATEGORY_LABELS[cat] || cat,
          tools,
        });
      }
    }

    return groups;
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

  return (
    <div className="enabled-tools-view">
      <div className="enabled-tools-view__header">
        <h3 className="enabled-tools-view__title">
          {isGlobalSettings ? 'Default Enabled Tools' : 'Session Tools'}
        </h3>
        <div className="enabled-tools-view__actions">
          <span className="enabled-tools-view__count">
            {enabledTools.size} of {availableTools.all.length} enabled
          </span>
          {!isGlobalSettings && sessionId && (
            <button
              className="enabled-tools-view__reset-btn"
              onClick={handleResetToDefaults}
              disabled={isSaving}
              title="Reset to default enabled tools"
            >
              Reset to Defaults
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
      </div>

      {isSaving && (
        <div className="enabled-tools-view__saving">Saving...</div>
      )}
    </div>
  );
});
