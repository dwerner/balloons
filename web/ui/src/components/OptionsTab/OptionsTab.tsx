/**
 * OptionsTab - Configuration panel for app settings
 *
 * Contains cards for:
 * - Logging: Toggle which log categories are written to server-side files
 */

import React, { useState, useCallback, useEffect, memo } from 'react';
import type { DebugLogServiceClient } from '../../../../generated/client';
import './OptionsTab.css';

// Known log categories with descriptions
const LOG_CATEGORIES = [
  { id: 'api', label: 'API', description: 'API requests, responses, and raw chunks' },
  { id: 'tool', label: 'Tool', description: 'Tool execution and results' },
  { id: 'json', label: 'JSON', description: 'JSON parsing errors and dumps' },
  { id: 'process', label: 'Process', description: 'Process lifecycle events' },
  { id: 'stream', label: 'Stream', description: 'Streaming events and timeouts' },
  { id: 'perf', label: 'Perf', description: 'Performance markers and timing' },
  { id: 'client', label: 'Client', description: 'Web UI client-side logs' },
] as const;

interface OptionsTabProps {
  debugLogClient?: DebugLogServiceClient;
  isConnected: boolean;
  debugEnabled?: boolean;
  onToggleDebug?: () => void;
}

export const OptionsTab = memo(function OptionsTab({
  debugLogClient,
  isConnected,
  debugEnabled = false,
  onToggleDebug,
}: OptionsTabProps) {
  const [enabledCategories, setEnabledCategories] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  // Load current categories on mount
  useEffect(() => {
    if (!debugLogClient || !isConnected) return;

    const loadCategories = async () => {
      try {
        const categories = await debugLogClient.getCategories();
        setEnabledCategories(categories);
      } catch (err) {
        console.error('Failed to load log categories:', err);
      }
    };

    loadCategories();
  }, [debugLogClient, isConnected]);

  const handleToggleCategory = useCallback(async (categoryId: string) => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      const isEnabled = enabledCategories.includes(categoryId);
      if (isEnabled) {
        await debugLogClient.disableCategory(categoryId);
        setEnabledCategories(prev => prev.filter(c => c !== categoryId));
      } else {
        await debugLogClient.enableCategory(categoryId);
        setEnabledCategories(prev => [...prev, categoryId]);
      }
    } catch (err) {
      console.error('Failed to toggle category:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient, enabledCategories]);

  const handleClearAll = useCallback(async () => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      await debugLogClient.clearCategories();
      setEnabledCategories([]);
    } catch (err) {
      console.error('Failed to clear categories:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient]);

  const handleEnableAll = useCallback(async () => {
    if (!debugLogClient) return;

    setIsLoading(true);
    try {
      const allIds = LOG_CATEGORIES.map(c => c.id);
      await debugLogClient.setCategories(allIds);
      setEnabledCategories(allIds);
    } catch (err) {
      console.error('Failed to enable all categories:', err);
    } finally {
      setIsLoading(false);
    }
  }, [debugLogClient]);

  if (!isConnected) {
    return (
      <div className="options-tab">
        <div className="options-tab__disconnected">
          Connect to server to configure options
        </div>
      </div>
    );
  }

  const hasAnyEnabled = enabledCategories.length > 0;

  return (
    <div className="options-tab">
      {/* Debug Logging Card */}
      <div className="options-card">
        <div className="options-card__header">
          <h3 className="options-card__title">Debug Logging</h3>
        </div>

        <div className="options-card__content">
          {/* Global debug toggle */}
          <label className="debug-toggle">
            <input
              type="checkbox"
              checked={debugEnabled}
              onChange={onToggleDebug}
            />
            <span className="debug-toggle__label">Enable debug logging</span>
            <span className="debug-toggle__description">
              Log to browser console and ~/.balloons/debug.log
            </span>
          </label>

          {/* Category filtering section */}
          <div className={`log-categories-section ${!debugEnabled ? 'log-categories-section--disabled' : ''}`}>
            <div className="options-card__section-header">
              <span className="options-card__section-title">Category Filtering</span>
              <span className="options-card__hint">
                {hasAnyEnabled
                  ? `${enabledCategories.length} categor${enabledCategories.length === 1 ? 'y' : 'ies'} enabled`
                  : 'Logging all categories'}
              </span>
            </div>

            <div className="log-categories">
              {LOG_CATEGORIES.map(({ id, label, description }) => {
                const isEnabled = enabledCategories.includes(id);
                return (
                  <label key={id} className="log-category">
                    <input
                      type="checkbox"
                      checked={isEnabled}
                      onChange={() => handleToggleCategory(id)}
                      disabled={isLoading || !debugEnabled}
                    />
                    <span className="log-category__label">{label}</span>
                    <span className="log-category__description">{description}</span>
                  </label>
                );
              })}
            </div>

            <div className="options-card__actions">
              <button
                className="options-btn options-btn--secondary"
                onClick={handleClearAll}
                disabled={isLoading || !hasAnyEnabled || !debugEnabled}
                title="Log all categories (no filtering)"
              >
                Clear Filter
              </button>
              <button
                className="options-btn options-btn--secondary"
                onClick={handleEnableAll}
                disabled={isLoading || !debugEnabled}
                title="Enable all categories"
              >
                Enable All
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

export default OptionsTab;
