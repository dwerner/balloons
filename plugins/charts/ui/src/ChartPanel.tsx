/**
 * ChartPanel Component
 *
 * Container for multiple charts with tab navigation.
 * Listens to chart domain events for real-time updates.
 */

import React, { useState, useEffect, useCallback } from 'react';
import ChartView, { ChartData } from './ChartView';
import './ChartPanel.css';

interface ChartPanelProps {
  /** Initial charts to display */
  initialCharts?: ChartData[];
  /** WebSocket message handler (optional, for event subscription) */
  onSubscribe?: (handler: (event: any) => void) => () => void;
}

export const ChartPanel: React.FC<ChartPanelProps> = ({
  initialCharts = [],
  onSubscribe,
}) => {
  const [charts, setCharts] = useState<Map<string, ChartData>>(
    new Map(initialCharts.map(c => [c.id, c]))
  );
  const [activeChartId, setActiveChartId] = useState<string | null>(
    initialCharts[0]?.id || null
  );

  // Handle domain events
  const handleEvent = useCallback((event: any) => {
    if (!event.type?.startsWith('chart_')) return;

    const payload = event.payload;

    switch (event.type) {
      case 'chart_created':
        setCharts(prev => {
          const next = new Map(prev);
          next.set(payload.chart_id, payload.config);
          return next;
        });
        setActiveChartId(payload.chart_id);
        break;

      case 'chart_data_updated':
        setCharts(prev => {
          const chart = prev.get(payload.chart_id);
          if (!chart) return prev;
          const next = new Map(prev);
          next.set(payload.chart_id, { ...chart, data: payload.data });
          return next;
        });
        break;

      case 'chart_style_updated':
        setCharts(prev => {
          const next = new Map(prev);
          next.set(payload.chart_id, payload.config);
          return next;
        });
        break;

      case 'chart_deleted':
        setCharts(prev => {
          const next = new Map(prev);
          next.delete(payload.chart_id);
          return next;
        });
        if (activeChartId === payload.chart_id) {
          const remaining = Array.from(charts.keys()).filter(id => id !== payload.chart_id);
          setActiveChartId(remaining[0] || null);
        }
        break;

      case 'chart_state_sync':
        if (payload.charts) {
          setCharts(new Map(payload.charts.map((c: ChartData) => [c.id, c])));
          if (!activeChartId && payload.charts.length > 0) {
            setActiveChartId(payload.charts[0].id);
          }
        }
        break;
    }
  }, [activeChartId, charts]);

  // Subscribe to events if handler provided
  useEffect(() => {
    if (onSubscribe) {
      return onSubscribe(handleEvent);
    }
  }, [onSubscribe, handleEvent]);

  const chartList = Array.from(charts.values());
  const activeChart = activeChartId ? charts.get(activeChartId) : null;

  if (chartList.length === 0) {
    return (
      <div className="chart-panel chart-panel--empty">
        <div className="chart-panel__empty-state">
          <span className="chart-panel__empty-icon">📊</span>
          <p>No charts yet</p>
          <p className="chart-panel__empty-hint">
            Use <code>chart_create</code> to create a chart
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="chart-panel">
      {/* Tab bar */}
      <div className="chart-panel__tabs">
        {chartList.map(chart => (
          <button
            key={chart.id}
            className={`chart-panel__tab ${chart.id === activeChartId ? 'chart-panel__tab--active' : ''}`}
            onClick={() => setActiveChartId(chart.id)}
            title={`${chart.name} (${chart.chartType})`}
          >
            <span className="chart-panel__tab-icon">
              {chart.chartType === 'line' && '📈'}
              {chart.chartType === 'bar' && '📊'}
              {chart.chartType === 'area' && '📉'}
              {chart.chartType === 'scatter' && '⚬'}
            </span>
            <span className="chart-panel__tab-name">{chart.name}</span>
            <span className="chart-panel__tab-count">{chart.data.length}</span>
          </button>
        ))}
      </div>

      {/* Chart display */}
      <div className="chart-panel__content">
        {activeChart ? (
          <ChartView
            chart={activeChart}
            height={400}
          />
        ) : (
          <div className="chart-panel__no-selection">
            Select a chart from the tabs above
          </div>
        )}
      </div>

      {/* Chart info */}
      {activeChart && (
        <div className="chart-panel__info">
          <span className="chart-panel__info-id">ID: {activeChart.id}</span>
          <span className="chart-panel__info-type">Type: {activeChart.chartType}</span>
          <span className="chart-panel__info-rows">Rows: {activeChart.data.length}</span>
        </div>
      )}
    </div>
  );
};

export default ChartPanel;
