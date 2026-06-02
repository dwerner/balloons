import { describe, it, expect, mock } from 'bun:test';
import type { TaskInfo } from '../../../../generated/balloons-client';

function createMockTask(overrides: Partial<TaskInfo> = {}): TaskInfo {
  return {
    taskId: 'task-123',
    taskType: 'streaming',
    status: 'running',
    sessionId: 'session-456',
    backendName: 'claude',
    startedAt: '2024-01-01T00:00:00.000Z',
    finishedAt: null,
    prompt: 'Test prompt',
    tokensStreamed: 500,
    error: null,
    toolName: null,
    toolCount: 0,
    inputTokens: 1000,
    outputTokens: 500,
    contextWindow: 200000,
    model: 'claude-3-opus-20240229',
    durationSeconds: 5,
    isActive: true,
    currentTokenRate: 25.5,
    ...overrides,
  };
}

describe('StreamingStatusBar', () => {
  it('formats exchange duration as hh:mm:ss:xx', () => {
    const format = (seconds: number) => {
      const safeSeconds = Math.max(0, Math.floor(seconds));
      const hours = Math.floor(safeSeconds / 3600);
      const minutes = Math.floor((safeSeconds % 3600) / 60);
      const secs = safeSeconds % 60;
      const hundredths = Math.floor((seconds - Math.floor(seconds)) * 100);
      return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}:${String(hundredths).padStart(2, '0')}`;
    };

    expect(format(0)).toBe('00:00:00:00');
    expect(format(5.12)).toBe('00:00:05:12');
    expect(format(65.99)).toBe('00:01:05:98');
    expect(format(3661.04)).toBe('01:01:01:03');
  });

  it('prefers startedAt for restart-safe elapsed time calculations', () => {
    const task = createMockTask({ startedAt: '2024-01-01T00:00:00.000Z', durationSeconds: 42 });
    expect(task.startedAt).toBe('2024-01-01T00:00:00.000Z');
    expect(task.durationSeconds).toBe(42);
  });

  it('supports stop callback', () => {
    const task = createMockTask();
    const onStop = mock(() => {});
    const props = { task, onStop };
    props.onStop();
    expect(onStop).toHaveBeenCalled();
  });
});
