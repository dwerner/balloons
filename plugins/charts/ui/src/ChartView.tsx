/**
 * ChartView Component
 *
 * Renders a single chart using Recharts.
 * Supports line, bar, area, and scatter chart types.
 */

import React, { useMemo } from 'react';
import {
  LineChart,
  BarChart,
  AreaChart,
  ScatterChart,
  Line,
  Bar,
  Area,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export interface ChartData {
  id: string;
  name: string;
  chartType: 'line' | 'bar' | 'area' | 'scatter';
  data: Array<{
    x: any;
    y: number;
    series?: string;
    label?: string;
  }>;
  style: {
    title?: string;
    xLabel?: string;
    yLabel?: string;
    colors?: string[];
    showGrid?: boolean;
    showLegend?: boolean;
    showDots?: boolean;
    lineWidth?: number;
    barGap?: number;
    areaOpacity?: number;
    animate?: boolean;
    yMin?: number;
    yMax?: number;
  };
}

interface ChartViewProps {
  chart: ChartData;
  width?: number | string;
  height?: number;
  /** Mini mode for preview cards - hides axes, legend, etc. */
  mini?: boolean;
}

const DEFAULT_COLORS = ['#8884d8', '#82ca9d', '#ffc658', '#ff7c43', '#a4de6c', '#d0ed57'];

export const ChartView: React.FC<ChartViewProps> = ({
  chart,
  width = '100%',
  height = 300,
  mini = false,
}) => {
  const { chartType, data, style } = chart;

  // Transform data for Recharts: group by x value, with series as separate keys
  const transformedData = useMemo(() => {
    const byX = new Map<string, Record<string, any>>();

    for (const row of data) {
      const xKey = String(row.x);
      if (!byX.has(xKey)) {
        byX.set(xKey, { x: row.x });
      }
      const entry = byX.get(xKey)!;
      const series = row.series || 'value';
      entry[series] = row.y;
    }

    return Array.from(byX.values());
  }, [data]);

  // Get unique series names
  const seriesNames = useMemo(() => {
    const names = new Set<string>();
    for (const row of data) {
      names.add(row.series || 'value');
    }
    return Array.from(names);
  }, [data]);

  const colors = style.colors || DEFAULT_COLORS;

  // Common chart props
  const chartProps = {
    data: transformedData,
    margin: mini
      ? { top: 5, right: 5, left: 5, bottom: 5 }
      : { top: 20, right: 30, left: 20, bottom: 20 },
  };

  const xAxisProps = {
    dataKey: 'x',
    label: style.xLabel ? { value: style.xLabel, position: 'bottom', offset: -5 } : undefined,
  };

  const yAxisProps = {
    label: style.yLabel ? { value: style.yLabel, angle: -90, position: 'insideLeft' } : undefined,
    domain: [style.yMin ?? 'auto', style.yMax ?? 'auto'] as [number | 'auto', number | 'auto'],
  };

  const renderChart = () => {
    switch (chartType) {
      case 'line':
        return (
          <LineChart {...chartProps}>
            {!mini && style.showGrid !== false && <CartesianGrid strokeDasharray="3 3" stroke="#444" />}
            {!mini && <XAxis {...xAxisProps} stroke="#888" />}
            {!mini && <YAxis {...yAxisProps} stroke="#888" />}
            {!mini && (
              <Tooltip
                contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                labelStyle={{ color: '#fff' }}
              />
            )}
            {!mini && style.showLegend !== false && seriesNames.length > 1 && <Legend />}
            {seriesNames.map((series, i) => (
              <Line
                key={series}
                type="monotone"
                dataKey={series}
                stroke={colors[i % colors.length]}
                strokeWidth={mini ? 1 : (style.lineWidth || 2)}
                dot={mini ? false : (style.showDots !== false)}
                isAnimationActive={!mini && style.animate !== false}
              />
            ))}
          </LineChart>
        );

      case 'bar':
        return (
          <BarChart {...chartProps} barGap={style.barGap || 4}>
            {!mini && style.showGrid !== false && <CartesianGrid strokeDasharray="3 3" stroke="#444" />}
            {!mini && <XAxis {...xAxisProps} stroke="#888" />}
            {!mini && <YAxis {...yAxisProps} stroke="#888" />}
            {!mini && (
              <Tooltip
                contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                labelStyle={{ color: '#fff' }}
              />
            )}
            {!mini && style.showLegend !== false && seriesNames.length > 1 && <Legend />}
            {seriesNames.map((series, i) => (
              <Bar
                key={series}
                dataKey={series}
                fill={colors[i % colors.length]}
                isAnimationActive={!mini && style.animate !== false}
              />
            ))}
          </BarChart>
        );

      case 'area':
        return (
          <AreaChart {...chartProps}>
            {!mini && style.showGrid !== false && <CartesianGrid strokeDasharray="3 3" stroke="#444" />}
            {!mini && <XAxis {...xAxisProps} stroke="#888" />}
            {!mini && <YAxis {...yAxisProps} stroke="#888" />}
            {!mini && (
              <Tooltip
                contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                labelStyle={{ color: '#fff' }}
              />
            )}
            {!mini && style.showLegend !== false && seriesNames.length > 1 && <Legend />}
            {seriesNames.map((series, i) => (
              <Area
                key={series}
                type="monotone"
                dataKey={series}
                stroke={colors[i % colors.length]}
                fill={colors[i % colors.length]}
                fillOpacity={style.areaOpacity ?? 0.3}
                isAnimationActive={!mini && style.animate !== false}
              />
            ))}
          </AreaChart>
        );

      case 'scatter':
        return (
          <ScatterChart {...chartProps}>
            {!mini && style.showGrid !== false && <CartesianGrid strokeDasharray="3 3" stroke="#444" />}
            {!mini && <XAxis {...xAxisProps} stroke="#888" type="number" dataKey="x" name={style.xLabel || 'x'} />}
            {!mini && <YAxis {...yAxisProps} stroke="#888" dataKey="y" name={style.yLabel || 'y'} />}
            {!mini && (
              <Tooltip
                contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333' }}
                labelStyle={{ color: '#fff' }}
                cursor={{ strokeDasharray: '3 3' }}
              />
            )}
            {!mini && style.showLegend !== false && seriesNames.length > 1 && <Legend />}
            {seriesNames.map((series, i) => (
              <Scatter
                key={series}
                name={series}
                data={transformedData.map(d => ({ x: d.x, y: d[series] })).filter(d => d.y !== undefined)}
                fill={colors[i % colors.length]}
                isAnimationActive={!mini && style.animate !== false}
              />
            ))}
          </ScatterChart>
        );

      default:
        return <div>Unknown chart type: {chartType}</div>;
    }
  };

  return (
    <div className={`chart-view ${mini ? 'chart-view--mini' : ''}`} style={{ width, height: mini ? height : height + 40 }}>
      {!mini && style.title && (
        <h3 style={{
          textAlign: 'center',
          margin: '0 0 8px 0',
          color: '#fff',
          fontSize: 14,
          fontWeight: 500,
        }}>
          {style.title}
        </h3>
      )}
      <ResponsiveContainer width="100%" height={height}>
        {renderChart()}
      </ResponsiveContainer>
    </div>
  );
};

export default ChartView;
