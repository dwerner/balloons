/**
 * DomainsTab - Container for dynamically loaded domain plugin UIs
 *
 * This tab displays UIs from loaded domain plugins. When a domain with UI
 * is loaded, its component appears here.
 *
 * Features:
 * - Lists available plugins
 * - Loads plugin UIs on demand
 * - Renders plugin components with proper context
 * - Handles plugin load/unload lifecycle
 */

import React, { useState, useEffect, useCallback } from 'react';
import { usePlugins, pluginRegistry, type PluginInfo, type PluginContext } from '../../plugins';
import type { SessionDataServiceClient } from '../../../../generated/balloons-client';
import './DomainsTab.css';

interface DomainsTabProps {
  /** Send a message to the LLM */
  sendMessage?: (message: string) => void;
  /** Current session ID */
  sessionId?: string;
  /** Session data service client for domain event subscriptions */
  sessionDataClient?: SessionDataServiceClient;
  /** Whether the LLM is currently responding (streaming) */
  isLLMResponding?: boolean;
}

export function DomainsTab({
  sendMessage,
  sessionId,
  sessionDataClient,
  isLLMResponding = false,
}: DomainsTabProps) {
  const { loaded, load, unload, isLoaded } = usePlugins();
  const [available, setAvailable] = useState<PluginInfo[]>([]);
  const [loading, setLoading] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [activePlugin, setActivePlugin] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);

  // Handle escape key to exit fullscreen
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isFullscreen]);

  // Fetch available plugins
  const refreshAvailable = useCallback(async () => {
    const plugins = await pluginRegistry.listAvailable();
    setAvailable(plugins);
  }, []);

  // Fetch on mount
  useEffect(() => {
    refreshAvailable();
  }, [refreshAvailable]);

  // Reload a plugin (unload then load to get new version)
  const handleReload = async (pluginId: string) => {
    if (loading.has(pluginId)) return;

    setLoading(prev => new Set(prev).add(pluginId));
    setError(null);

    try {
      unload(pluginId);
      // Refresh available to get updated manifest with new builtAt
      await refreshAvailable();
      await load(pluginId);
    } catch (err) {
      setError(`Failed to reload ${pluginId}: ${err}`);
    } finally {
      setLoading(prev => {
        const next = new Set(prev);
        next.delete(pluginId);
        return next;
      });
    }
  };

  // Create context for plugin components
  const createPluginContext = useCallback((): PluginContext => {
    return {
      sendMessage,
      sessionId,
      isLLMResponding,
      // Wrap sessionDataClient to filter by domain
      subscribeToDomainEvents: sessionDataClient
        ? (domainId, callback) => {
            return sessionDataClient.sessionDataDomainEvent((event) => {
              if (event.domainId === domainId) {
                callback(event);
              }
            });
          }
        : undefined,
      requestDomainState: sessionDataClient
        ? async (domainId) => {
            if (!sessionId) return false;
            return sessionDataClient.requestDomainState(sessionId, domainId);
          }
        : undefined,
    };
  }, [sendMessage, sessionId, sessionDataClient, isLLMResponding]);

  // Handle loading a plugin
  const handleLoad = async (pluginId: string) => {
    if (loading.has(pluginId)) return;

    setLoading(prev => new Set(prev).add(pluginId));
    setError(null);

    try {
      await load(pluginId);
      setActivePlugin(pluginId);
    } catch (err) {
      setError(`Failed to load ${pluginId}: ${err}`);
    } finally {
      setLoading(prev => {
        const next = new Set(prev);
        next.delete(pluginId);
        return next;
      });
    }
  };

  // Handle unloading a plugin
  const handleUnload = (pluginId: string) => {
    unload(pluginId);
    if (activePlugin === pluginId) {
      // Switch to another loaded plugin or null
      const remaining = loaded.filter(p => p.id !== pluginId);
      const nextPlugin = remaining[0];
      setActivePlugin(nextPlugin ? nextPlugin.id : null);
    }
  };

  // Get the active plugin's component
  const activePluginManifest = loaded.find(p => p.id === activePlugin);
  const PluginComponent = activePluginManifest?.component;

  return (
    <div className={`domains-tab ${isFullscreen ? 'domains-tab--fullscreen' : ''}`}>
      {/* Plugin selector bar */}
      <div className="domains-plugin-bar">
        <div className="domains-loaded-plugins">
          {loaded.map(plugin => (
            <button
              key={plugin.id}
              className={`domains-plugin-button ${activePlugin === plugin.id ? 'active' : ''}`}
              onClick={() => setActivePlugin(plugin.id)}
            >
              {plugin.tab?.icon && <span className="plugin-icon">{plugin.tab.icon}</span>}
              {plugin.tab?.label || plugin.name}
              <span
                className="plugin-reload"
                onClick={(e) => {
                  e.stopPropagation();
                  handleReload(plugin.id);
                }}
                title="Reload plugin (get latest version)"
              >
                ↻
              </span>
              <span
                className="plugin-close"
                onClick={(e) => {
                  e.stopPropagation();
                  handleUnload(plugin.id);
                }}
                title="Unload plugin"
              >
                ×
              </span>
            </button>
          ))}
        </div>

        <div className="domains-available-plugins">
          <select
            value=""
            onChange={(e) => {
              if (e.target.value) {
                handleLoad(e.target.value);
              }
            }}
          >
            <option value="">+ Load Plugin...</option>
            {available
              .filter(p => !isLoaded(p.id))
              .map(p => (
                <option key={p.id} value={p.id} disabled={loading.has(p.id)}>
                  {p.id} {loading.has(p.id) ? '(loading...)' : ''}
                </option>
              ))}
          </select>
        </div>

        {/* Fullscreen toggle - show when any plugins are loaded */}
        {loaded.length > 0 && (
          <button
            className="domains-fullscreen-button"
            onClick={() => setIsFullscreen(!isFullscreen)}
            title={isFullscreen ? 'Exit fullscreen (Esc)' : 'Enter fullscreen'}
          >
            {isFullscreen ? '⤓' : '⤢'}
          </button>
        )}
      </div>

      {/* Error message */}
      {error && (
        <div className="domains-error">
          {error}
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Plugin content area */}
      <div className="domains-content">
        {PluginComponent ? (
          <PluginComponent {...createPluginContext()} />
        ) : loaded.length === 0 ? (
          <div className="domains-empty">
            <h3>No Plugins Loaded</h3>
            <p>Select a plugin from the dropdown above to load it.</p>
            {available.length > 0 && (
              <div className="domains-available-list">
                <h4>Available Plugins:</h4>
                <ul>
                  {available.map(p => (
                    <li key={p.id}>
                      <button
                        onClick={() => handleLoad(p.id)}
                        disabled={loading.has(p.id)}
                      >
                        {p.id}
                      </button>
                      <span className="plugin-version">v{p.manifest.version}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="domains-empty">
            <p>Select a loaded plugin from the tabs above.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default DomainsTab;
