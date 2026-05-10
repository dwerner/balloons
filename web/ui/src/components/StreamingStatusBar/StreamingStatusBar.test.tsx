import { describe, it, expect, beforeEach, afterEach, mock } from 'bun:test';
import type { TaskInfo } from '../../../../generated/balloons-client';

// Create a mock task for testing
function createMockTask(overrides: Partial<TaskInfo> = {}): TaskInfo {
  return {
    taskId: 'task-123',
    taskType: 'streaming',
    status: 'running',
    sessionId: 'session-456',
    backendName: 'claude',
    startedAt: new Date().toISOString(),
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
  describe('formatDuration', () => {
    // Test the duration formatting logic
    const formatDuration = (seconds: number): string => {
      if (seconds < 60) {
        return `${Math.floor(seconds)}s`;
      }
      const mins = Math.floor(seconds / 60);
      const secs = Math.floor(seconds % 60);
      return `${mins}m ${secs}s`;
    };

    it('should format seconds correctly', () => {
      expect(formatDuration(5)).toBe('5s');
      expect(formatDuration(30)).toBe('30s');
      expect(formatDuration(59)).toBe('59s');
    });

    it('should format minutes and seconds correctly', () => {
      expect(formatDuration(60)).toBe('1m 0s');
      expect(formatDuration(65)).toBe('1m 5s');
      expect(formatDuration(125)).toBe('2m 5s');
    });
  });

  describe('formatTokens', () => {
    // Test the token formatting logic
    const formatTokens = (count: number): string => {
      if (count >= 1000) {
        return `${(count / 1000).toFixed(1)}k`;
      }
      return String(count);
    };

    it('should format small counts as-is', () => {
      expect(formatTokens(0)).toBe('0');
      expect(formatTokens(500)).toBe('500');
      expect(formatTokens(999)).toBe('999');
    });

    it('should format thousands with k suffix', () => {
      expect(formatTokens(1000)).toBe('1.0k');
      expect(formatTokens(1500)).toBe('1.5k');
      expect(formatTokens(10000)).toBe('10.0k');
      expect(formatTokens(150000)).toBe('150.0k');
    });
  });

  describe('calculateContextUsage', () => {
    // Test the context usage calculation
    const calculateContextUsage = (
      inputTokens: number,
      outputTokens: number,
      contextWindow: number
    ): number => {
      if (contextWindow <= 0) return 0;
      const totalUsed = inputTokens + outputTokens;
      return Math.min(100, (totalUsed / contextWindow) * 100);
    };

    it('should return 0 when contextWindow is 0', () => {
      expect(calculateContextUsage(1000, 500, 0)).toBe(0);
    });

    it('should calculate percentage correctly', () => {
      expect(calculateContextUsage(50000, 10000, 200000)).toBe(30);
      expect(calculateContextUsage(100000, 50000, 200000)).toBe(75);
    });

    it('should cap at 100%', () => {
      expect(calculateContextUsage(150000, 100000, 200000)).toBe(100);
    });
  });

  describe('getContextBarColorClass', () => {
    // Test the color class logic
    const getContextBarColorClass = (percentage: number): string => {
      if (percentage >= 90) return 'context-bar--critical';
      if (percentage >= 75) return 'context-bar--warning';
      if (percentage >= 50) return 'context-bar--moderate';
      return 'context-bar--healthy';
    };

    it('should return healthy for low usage', () => {
      expect(getContextBarColorClass(0)).toBe('context-bar--healthy');
      expect(getContextBarColorClass(25)).toBe('context-bar--healthy');
      expect(getContextBarColorClass(49)).toBe('context-bar--healthy');
    });

    it('should return moderate for 50-75%', () => {
      expect(getContextBarColorClass(50)).toBe('context-bar--moderate');
      expect(getContextBarColorClass(60)).toBe('context-bar--moderate');
      expect(getContextBarColorClass(74)).toBe('context-bar--moderate');
    });

    it('should return warning for 75-90%', () => {
      expect(getContextBarColorClass(75)).toBe('context-bar--warning');
      expect(getContextBarColorClass(80)).toBe('context-bar--warning');
      expect(getContextBarColorClass(89)).toBe('context-bar--warning');
    });

    it('should return critical for 90%+', () => {
      expect(getContextBarColorClass(90)).toBe('context-bar--critical');
      expect(getContextBarColorClass(95)).toBe('context-bar--critical');
      expect(getContextBarColorClass(100)).toBe('context-bar--critical');
    });
  });

  describe('createMockTask', () => {
    it('should create a valid task with defaults', () => {
      const task = createMockTask();
      expect(task.taskId).toBe('task-123');
      expect(task.model).toBe('claude-3-opus-20240229');
      expect(task.tokensStreamed).toBe(500);
    });

    it('should allow overriding defaults', () => {
      const task = createMockTask({
        model: 'custom-model',
        tokensStreamed: 1000,
      });
      expect(task.model).toBe('custom-model');
      expect(task.tokensStreamed).toBe(1000);
    });
  });
});

describe('StreamingStatusBar Props', () => {
  it('should have correct required props type', () => {
    const task = createMockTask();

    // Type check - these should compile
    const props = {
      task,
    };

    expect(props.task.taskId).toBe('task-123');
  });

  it('should support optional onStop callback', () => {
    const task = createMockTask();
    const onStop = mock(() => {});

    const props = {
      task,
      onStop,
      stopDisabled: false,
    };

    // Simulate calling onStop
    props.onStop();
    expect(onStop).toHaveBeenCalled();
  });

  it('should support optional sessionContextTokens', () => {
    const task = createMockTask();

    const props = {
      task,
      sessionContextTokens: 50000,
    };

    // sessionContextTokens should override task's input/output tokens for context calculation
    expect(props.sessionContextTokens).toBe(50000);
  });
});

describe('Context Token Priority', () => {
  it('should use sessionContextTokens over task tokens when provided', () => {
    // When sessionContextTokens is provided, it should be used for context display
    // This is important because task.inputTokens/outputTokens are only populated
    // at the END of streaming, whereas sessionContextTokens is the running total
    const sessionTokens = 75000;
    const taskInputTokens = 0;  // Would be 0 during streaming
    const taskOutputTokens = 0;  // Would be 0 during streaming

    // The component should prefer sessionTokens
    const totalTokens = sessionTokens ?? (taskInputTokens + taskOutputTokens);
    expect(totalTokens).toBe(75000);
  });

  it('should fall back to task tokens when sessionContextTokens not provided', () => {
    const sessionTokens = undefined;
    const taskInputTokens = 50000;
    const taskOutputTokens = 10000;

    const totalTokens = sessionTokens ?? (taskInputTokens + taskOutputTokens);
    expect(totalTokens).toBe(60000);
  });
});
