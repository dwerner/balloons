/**
 * Utility functions for safely handling tool input values.
 *
 * Some models (e.g., Qwen) may send non-string values for fields that
 * should be strings. These utilities handle conversion gracefully.
 */

/**
 * Safely convert a value to string.
 * - strings pass through unchanged
 * - null/undefined become empty string
 * - objects/arrays become JSON representation
 * - other types get String() conversion
 */
export function ensureString(value: unknown, defaultValue = ''): string {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return defaultValue;
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return '[object]';
    }
  }
  return String(value);
}

/**
 * Safely get a string value from a tool input object.
 */
export function getStringInput(
  input: Record<string, unknown>,
  key: string,
  defaultValue = ''
): string {
  return ensureString(input[key], defaultValue);
}

/**
 * Safely get a string value from a tool input object with fallback keys.
 */
export function getStringInputWithFallback(
  input: Record<string, unknown>,
  keys: string[],
  defaultValue = ''
): string {
  for (const key of keys) {
    if (key in input) {
      return ensureString(input[key], defaultValue);
    }
  }
  return defaultValue;
}

/**
 * Safely get a number value from a tool input object.
 */
export function getNumberInput(
  input: Record<string, unknown>,
  key: string,
  defaultValue = 0
): number {
  const value = input[key];
  if (typeof value === 'number') return value;
  if (typeof value === 'string') {
    const parsed = parseFloat(value);
    return isNaN(parsed) ? defaultValue : parsed;
  }
  return defaultValue;
}

/**
 * Safely get a boolean value from a tool input object.
 */
export function getBooleanInput(
  input: Record<string, unknown>,
  key: string,
  defaultValue = false
): boolean {
  const value = input[key];
  if (typeof value === 'boolean') return value;
  if (typeof value === 'string') {
    return value.toLowerCase() === 'true';
  }
  return defaultValue;
}
