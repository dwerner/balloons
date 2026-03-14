/**
 * ChartsTab - Interactive charts panel for the Charts domain plugin
 *
 * Two-tab layout:
 * - Browse: Grid of chart cards for browsing all charts
 * - View: Full chart visualization with controls
 *
 * Features:
 * - Multiple chart support
 * - Real-time updates from chart domain events
 * - State sync on tab switch / reconnection
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import ChartView, { ChartData } from './ChartView';
import './ChartPanel.css';

// Confirm dialog options
interface ConfirmOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'default' | 'danger' | 'warning' | 'success';
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

// Domain event structure
export interface DomainEventData {
  sessionId: string;
  domainId: string;
  eventType: string;
  data: Record<string, unknown>;
}

type TabMode = 'browse' | 'view';

export function ChartsTab({
  sendMessage,
  sessionId,
  subscribeToDomainEvents,
  requestDomainState,
  isLLMResponding = false,
  confirm,
  callDomainMethod,
}: PluginContext) {
  const [charts, setCharts] = useState<Map<string, ChartData>>(new Map());
  const [activeChartId, setActiveChartId] = useState<string | null>(null);
  const [tabMode, setTabMode] = useState<TabMode>('browse');

  // Subscribe to domain events
  useEffect(() => {
    if (!subscribeToDomainEvents || !sessionId) return;

    console.log('[ChartsTab] Subscribing to domain events for session:', sessionId);

    const unsubscribe = subscribeToDomainEvents('charts', (event) => {
      console.log('[ChartsTab] Received domain event:', event);
      // Charts are global - process all chart events regardless of session
      console.log('[ChartsTab] Processing chart event:', event.eventType);
      const data = event.data;

      switch (event.eventType) {
        case 'chart_created': {
          const config = data.config as ChartData;
          const chartId = data.chartId as string || data.chart_id as string;
          console.log('[ChartsTab] Chart created:', chartId, config);
          setCharts(prev => {
            const next = new Map(prev);
            next.set(chartId, config);
            return next;
          });
          setActiveChartId(chartId);
          setTabMode('view');
          break;
        }

        case 'chart_data_updated': {
          const chartId = data.chartId as string || data.chart_id as string;
          const newData = data.data as ChartData['data'];
          console.log('[ChartsTab] Chart data updated:', chartId, newData?.length, 'rows');
          setCharts(prev => {
            const chart = prev.get(chartId);
            if (!chart) return prev;
            const next = new Map(prev);
            next.set(chartId, { ...chart, data: newData });
            return next;
          });
          break;
        }

        case 'chart_style_updated': {
          const chartId = data.chartId as string || data.chart_id as string;
          const config = data.config as ChartData;
          console.log('[ChartsTab] Chart style updated:', chartId);
          setCharts(prev => {
            const next = new Map(prev);
            next.set(chartId, config);
            return next;
          });
          break;
        }

        case 'chart_deleted': {
          const chartId = data.chartId as string || data.chart_id as string;
          console.log('[ChartsTab] Chart deleted:', chartId);
          setCharts(prev => {
            const next = new Map(prev);
            next.delete(chartId);
            return next;
          });
          setActiveChartId(current => {
            if (current === chartId) {
              const remaining = Array.from(charts.keys()).filter(id => id !== chartId);
              return remaining[0] || null;
            }
            return current;
          });
          break;
        }

        case 'chart_state_sync':
        case 'charts_state_sync': {
          // Handle both event names (domain emits chart_state_sync, requestDomainState emits charts_state_sync)
          const chartsList = data.charts as ChartData[] | undefined;
          console.log('[ChartsTab] State sync:', chartsList?.length, 'charts');
          if (chartsList) {
            setCharts(new Map(chartsList.map(c => [c.id, c])));
            setActiveChartId(current => {
              if (!current && chartsList.length > 0) {
                return chartsList[0].id;
              }
              return current;
            });
          }
          break;
        }
      }
    });

    return unsubscribe;
  }, [subscribeToDomainEvents, sessionId, charts]);

  // Request current charts state on mount (for tab switching / page reload)
  useEffect(() => {
    if (!requestDomainState || !sessionId) return;

    console.log('[ChartsTab] Requesting charts state for session:', sessionId);
    requestDomainState('charts').then((hasState) => {
      console.log('[ChartsTab] State request result:', hasState);
    }).catch((err) => {
      console.warn('[ChartsTab] Failed to request domain state:', err);
    });
  }, [requestDomainState, sessionId]);

  const chartList = useMemo(() => Array.from(charts.values()), [charts]);
  const activeChart = activeChartId ? charts.get(activeChartId) : null;

  // Handle manual sync request
  const handleSync = useCallback(() => {
    if (requestDomainState && sessionId) {
      requestDomainState('charts').catch(console.error);
    }
  }, [requestDomainState, sessionId]);

  // Handle selecting a chart from browse view
  const handleSelectChart = useCallback((chartId: string) => {
    setActiveChartId(chartId);
    setTabMode('view');
  }, []);

  // Handle deleting a chart via @ws_expose method
  const handleDeleteChart = useCallback(async (chartId: string, e: React.MouseEvent) => {
    e.stopPropagation(); // Don't trigger card click
    if (!callDomainMethod) return;

    const chartName = charts.get(chartId)?.name || chartId;

    // Use app confirm dialog if available, otherwise just delete
    if (confirm) {
      const confirmed = await confirm({
        title: 'Delete Chart',
        message: `Delete chart "${chartName}"? This cannot be undone.`,
        confirmText: 'Delete',
        variant: 'danger',
      });
      if (!confirmed) return;
    }

    // Call the @ws_expose method directly
    try {
      const result = await callDomainMethod('chartDelete', { chart_id: chartId });
      if (result && result.error) {
        console.error('[ChartsTab] Delete failed:', result.error);
      }
    } catch (e) {
      console.error('[ChartsTab] Delete failed:', e);
    }
  }, [callDomainMethod, confirm, charts]);

  // Get chart type icon
  const getChartIcon = (chartType: string) => {
    switch (chartType) {
      case 'line': return '📈';
      case 'bar': return '📊';
      case 'area': return '📉';
      case 'scatter': return '⚬';
      default: return '📊';
    }
  };

  // Render empty state
  if (chartList.length === 0) {
    return (
      <div className="chart-panel chart-panel--empty">
        <div className="chart-panel__empty-state">
          <span className="chart-panel__empty-icon">📊</span>
          <p>No charts available</p>
          <p className="chart-panel__empty-hint">
            Create charts using <code>chart_create</code> tool.
          </p>
          {requestDomainState && (
            <button
              className="chart-panel__create-button"
              onClick={handleSync}
            >
              🔄 Refresh
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="chart-panel">
      {/* Mode tabs */}
      <div className="chart-panel__mode-tabs">
        <button
          className={`chart-panel__mode-tab ${tabMode === 'browse' ? 'chart-panel__mode-tab--active' : ''}`}
          onClick={() => setTabMode('browse')}
        >
          📋 Browse ({chartList.length})
        </button>
        <button
          className={`chart-panel__mode-tab ${tabMode === 'view' ? 'chart-panel__mode-tab--active' : ''}`}
          onClick={() => setTabMode('view')}
          disabled={!activeChart}
        >
          📊 View {activeChart ? `- ${activeChart.name}` : ''}
        </button>
        <div className="chart-panel__mode-spacer" />
        <button
          className="chart-panel__sync-button"
          onClick={handleSync}
          title="Refresh charts"
        >
          🔄
        </button>
      </div>

      {/* Browse mode - grid of chart cards */}
      {tabMode === 'browse' && (
        <div className="chart-panel__browse">
          <div className="chart-panel__grid">
            {chartList.map(chart => (
              <div
                key={chart.id}
                className={`chart-panel__card ${chart.id === activeChartId ? 'chart-panel__card--active' : ''}`}
                onClick={() => handleSelectChart(chart.id)}
              >
                <div className="chart-panel__card-header">
                  <span className="chart-panel__card-icon">{getChartIcon(chart.chartType)}</span>
                  <span className="chart-panel__card-type">{chart.chartType}</span>
                </div>
                <div className="chart-panel__card-name">{chart.name}</div>
                <div className="chart-panel__card-meta">
                  <span>{chart.data.length} data points</span>
                  <span className="chart-panel__card-id">{chart.id}</span>
                </div>
                <button
                  className="chart-panel__card-delete"
                  onClick={(e) => handleDeleteChart(chart.id, e)}
                  title="Delete chart"
                >
                  🗑️
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* View mode - full chart display */}
      {tabMode === 'view' && (
        <div className="chart-panel__view">
          {activeChart ? (
            <>
              {/* Chart selector when in view mode */}
              <div className="chart-panel__selector">
                <select
                  value={activeChartId || ''}
                  onChange={(e) => setActiveChartId(e.target.value)}
                  className="chart-panel__select"
                >
                  {chartList.map(chart => (
                    <option key={chart.id} value={chart.id}>
                      {getChartIcon(chart.chartType)} {chart.name} ({chart.data.length} pts)
                    </option>
                  ))}
                </select>
                <button
                  className="chart-panel__delete-button"
                  onClick={(e) => activeChartId && handleDeleteChart(activeChartId, e)}
                  title="Delete this chart"
                >
                  🗑️ Delete
                </button>
              </div>

              {/* Full chart view */}
              <div className="chart-panel__content">
                <ChartView chart={activeChart} height={400} />
              </div>

              {/* Chart info bar */}
              <div className="chart-panel__info">
                <span className="chart-panel__info-id">ID: {activeChart.id}</span>
                <span className="chart-panel__info-type">Type: {activeChart.chartType}</span>
                <span className="chart-panel__info-rows">Rows: {activeChart.data.length}</span>
                {activeChart.style?.title && (
                  <span className="chart-panel__info-title">Title: {activeChart.style.title}</span>
                )}
              </div>
            </>
          ) : (
            <div className="chart-panel__no-selection">
              No chart selected. Go to Browse tab to select a chart.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ChartsTab;
