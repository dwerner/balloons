/**
 * DebugPane Demo Component
 *
 * A simple demo showing the DebugPane in action with mock data.
 * Useful for development and manual testing.
 *
 * Usage:
 * ```tsx
 * import { DebugPaneDemo } from './components/DebugPane/DebugPaneDemo';
 *
 * function App() {
 *   return <DebugPaneDemo />;
 * }
 * ```
 */

import React, { useState, useCallback } from 'react';
import { DebugPane } from './DebugPane';
import type { LogEntry, LogLevel } from './DebugPaneTypes';

// Generate mock entries for demo
function generateMockEntries(): LogEntry[] {
  const entries: LogEntry[] = [
    {
      seq: 1,
      level: 'info',
      message: 'Session started',
      timestamp: '14:30:00.000',
      category: 'session',
      sessionId: 'abc-123',
    },
    {
      seq: 2,
      level: 'debug',
      message: 'Loading configuration from ~/.balloons/config.json',
      timestamp: '14:30:00.050',
      category: 'config',
    },
    {
      seq: 3,
      level: 'trace',
      message: 'Scroll event: y=150',
      timestamp: '14:30:00.100',
    },
    {
      seq: 4,
      level: 'perf',
      message: 'render_chat_log: 12.5ms',
      timestamp: '14:30:00.150',
      category: 'perf',
      details: { elapsed_ms: 12.5, turn_count: 5 },
    },
    {
      seq: 5,
      level: 'info',
      message: 'Connected to Claude API',
      timestamp: '14:30:00.200',
      category: 'api',
    },
    {
      seq: 6,
      level: 'debug',
      message: 'Starting streaming response',
      timestamp: '14:30:00.250',
      category: 'stream',
      runId: '12345',
    },
    {
      seq: 7,
      level: 'warning',
      message: 'Rate limit approaching: 80% used',
      timestamp: '14:30:00.300',
      category: 'api',
      details: { used: 80, limit: 100 },
    },
    {
      seq: 8,
      level: 'perf',
      message: '[stream_complete]',
      timestamp: '14:30:00.350',
      category: 'perf',
      details: { total_tokens: 1500, duration_ms: 2340 },
    },
    {
      seq: 9,
      level: 'error',
      message: 'Tool execution failed: FileNotFoundError',
      timestamp: '14:30:00.400',
      category: 'tool',
      details: { tool: 'Read', path: '/nonexistent/file.txt' },
    },
    {
      seq: 10,
      level: 'info',
      message: 'Session saved to storage',
      timestamp: '14:30:00.450',
      category: 'storage',
    },
  ];
  return entries;
}

export function DebugPaneDemo() {
  const [entries, setEntries] = useState<LogEntry[]>(generateMockEntries);
  const [copiedText, setCopiedText] = useState<string>('');
  const [seqCounter, setSeqCounter] = useState(11);

  const handleLogLineCopy = useCallback((text: string) => {
    setCopiedText(text);
    // Clear after 3 seconds
    setTimeout(() => setCopiedText(''), 3000);
  }, []);

  const handleClear = useCallback(() => {
    setEntries([]);
    setSeqCounter(1);
  }, []);

  const addRandomEntry = useCallback(() => {
    const levels: LogLevel[] = ['trace', 'debug', 'perf', 'info', 'warning', 'error'];
    const levelIndex = Math.floor(Math.random() * levels.length);
    const level = levels[levelIndex] ?? 'info';
    const messages: Record<LogLevel, string[]> = {
      trace: ['Scroll event', 'Mouse move', 'Focus change'],
      debug: ['Processing message', 'Loading state', 'Updating cache'],
      perf: ['render: 15ms', 'api_call: 200ms', 'parse: 5ms'],
      info: ['User action', 'State update', 'Connection established'],
      warning: ['Deprecated API', 'Slow response', 'Memory pressure'],
      error: ['Connection failed', 'Parse error', 'Timeout'],
    };

    const levelMessages = messages[level];
    const msgIndex = Math.floor(Math.random() * levelMessages.length);
    const msg = levelMessages[msgIndex] ?? 'Unknown message';
    const now = new Date();
    const timestamp = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}.${now.getMilliseconds().toString().padStart(3, '0')}`;

    const newEntry: LogEntry = {
      seq: seqCounter,
      level,
      message: msg,
      timestamp,
    };

    setEntries((prev) => [...prev, newEntry]);
    setSeqCounter((prev) => prev + 1);
  }, [seqCounter]);

  const addError = useCallback(() => {
    const now = new Date();
    const timestamp = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}.${now.getMilliseconds().toString().padStart(3, '0')}`;

    const newEntry: LogEntry = {
      seq: seqCounter,
      level: 'error',
      message: 'Critical error occurred!',
      timestamp,
      category: 'system',
      details: { code: 'ERR_CRITICAL', recoverable: false },
    };

    setEntries((prev) => [...prev, newEntry]);
    setSeqCounter((prev) => prev + 1);
  }, [seqCounter]);

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Main content area */}
      <div style={{ flex: 1, padding: '20px', background: '#1a1a1a', color: '#e0e0e0' }}>
        <h2>DebugPane Demo</h2>
        <p>This demonstrates the DebugPane component with mock data.</p>

        <div style={{ display: 'flex', gap: '10px', marginTop: '20px' }}>
          <button onClick={addRandomEntry}>Add Random Entry</button>
          <button onClick={addError} style={{ background: '#e53935', color: 'white' }}>
            Add Error (triggers auto-expand)
          </button>
          <button onClick={handleClear}>Clear All</button>
        </div>

        {copiedText && (
          <div
            style={{
              marginTop: '20px',
              padding: '10px',
              background: '#333',
              borderRadius: '4px',
              fontFamily: 'monospace',
              fontSize: '12px',
            }}
          >
            <strong>Ctrl+Click copied:</strong>
            <br />
            {copiedText}
          </div>
        )}

        <div style={{ marginTop: '20px', color: '#888', fontSize: '14px' }}>
          <p>Features to test:</p>
          <ul>
            <li>Click header to expand/collapse</li>
            <li>Click level buttons (T/D/P/I/W/E) to filter</li>
            <li>Ctrl+click a log entry to copy it</li>
            <li>Add an error to see auto-expand with red border</li>
            <li>Note the error count badge in the header</li>
          </ul>
        </div>
      </div>

      {/* DebugPane at bottom */}
      <DebugPane
        entries={entries}
        onLogLineCopy={handleLogLineCopy}
        onClear={handleClear}
        autoExpandOnError={true}
      />
    </div>
  );
}

export default DebugPaneDemo;
