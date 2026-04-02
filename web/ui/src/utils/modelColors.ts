/**
 * Model Colors - Color mappings for different LLM models and backends
 *
 * Provides colors for the streaming indicator based on the active model/backend.
 * Colors can be customized via config, with sensible defaults for common models.
 */

// Default color palette for models
// Keys are matched against model name or backend name (case-insensitive, partial match)
export const DEFAULT_MODEL_COLORS: Record<string, string> = {
  // Claude models (various shades of orange/terracotta - Anthropic brand)
  'claude-opus': '#FF6B35',     // Vibrant orange
  'claude-sonnet': '#E85D04',   // Deep orange
  'claude-4': '#E85D04',        // Claude 4.x fallback
  'claude-3.5': '#F48C06',      // Medium orange
  'claude-3': '#FAA307',        // Light orange
  'claude': '#E85D04',          // Generic Claude fallback

  // OpenAI models (green shades - OpenAI brand)
  'gpt-4o': '#10B981',          // Emerald green
  'gpt-4-turbo': '#059669',     // Dark emerald
  'gpt-4': '#047857',           // Forest green
  'gpt-3.5': '#34D399',         // Light emerald
  'chatgpt': '#10B981',         // ChatGPT fallback
  'openai': '#10B981',          // OpenAI fallback

  // Meta/Llama models (blue shades - Meta brand)
  'llama-3.3': '#3B82F6',       // Bright blue
  'llama-3.2': '#2563EB',       // Medium blue
  'llama-3.1': '#1D4ED8',       // Dark blue
  'llama-3': '#60A5FA',         // Light blue
  'llama-2': '#93C5FD',         // Very light blue
  'llama': '#3B82F6',           // Llama fallback
  'codellama': '#6366F1',       // Indigo for code llama

  // Mistral models (purple shades)
  'mistral-large': '#8B5CF6',   // Vibrant purple
  'mistral-medium': '#A78BFA',  // Medium purple
  'mistral-small': '#C4B5FD',   // Light purple
  'mixtral': '#7C3AED',         // Deep purple for mixtral
  'mistral': '#8B5CF6',         // Mistral fallback

  // Google models (Google blue/red)
  'gemini-2': '#EA4335',        // Google red
  'gemini-1.5': '#4285F4',      // Google blue
  'gemini-pro': '#4285F4',      // Google blue
  'gemini': '#4285F4',          // Gemini fallback
  'palm': '#FBBC04',            // Google yellow

  // Cohere models (coral/pink)
  'command-r': '#F43F5E',       // Rose
  'command': '#FB7185',         // Light rose
  'cohere': '#F43F5E',          // Cohere fallback

  // DeepSeek models (teal)
  'deepseek-r1': '#14B8A6',     // Teal
  'deepseek-v3': '#0D9488',     // Dark teal
  'deepseek-coder': '#2DD4BF',  // Light teal
  'deepseek': '#14B8A6',        // DeepSeek fallback

  // Qwen models (amber/gold)
  'qwen-2.5': '#F59E0B',        // Amber
  'qwen-2': '#D97706',          // Dark amber
  'qwen': '#F59E0B',            // Qwen fallback

  // xAI / Grok (red)
  'grok': '#DC2626',            // Red

  // Local/self-hosted (gray/silver)
  'local': '#9CA3AF',           // Gray
  'ollama': '#6B7280',          // Dark gray
  'llamacpp': '#9CA3AF',        // Gray
  'gguf': '#9CA3AF',            // Gray
  'nvidia': '#76B900',          // NVIDIA green (for NIM/API)

  // Backends (used when model name not matched)
  'openrouter': '#A855F7',      // Purple for OpenRouter
  'together': '#EC4899',        // Pink for Together.ai
  'groq': '#22D3EE',            // Cyan for Groq
  'fireworks': '#F97316',       // Orange for Fireworks

  // Default fallback
  'default': '#4ADE80',         // Original green (should rarely be used now)
};

/**
 * Get the color for a model/backend combination
 *
 * @param model - The model name (e.g., "claude-3.5-sonnet", "gpt-4o")
 * @param backendName - The backend name (e.g., "claude", "openrouter")
 * @param customColors - Optional custom color overrides from config
 * @returns CSS color value
 */
export function getModelColor(
  model: string | undefined | null,
  backendName: string | undefined | null,
  customColors?: Record<string, string>
): string {
  // Merge custom colors with defaults (custom takes precedence)
  const colors = customColors ? { ...DEFAULT_MODEL_COLORS, ...customColors } : DEFAULT_MODEL_COLORS;

  // Normalize for matching (lowercase)
  const modelLower = (model || '').toLowerCase();
  const backendLower = (backendName || '').toLowerCase();

  // Try to match model name first (more specific)
  if (modelLower) {
    // Check for exact match first
    if (colors[modelLower]) {
      return colors[modelLower];
    }

    // Check for partial matches - prefer matches at the start of the string
    const sortedKeys = Object.keys(colors).filter(k => k !== 'default');

    // First pass: check if model STARTS with any key (most specific)
    for (const key of sortedKeys.sort((a, b) => b.length - a.length)) {
      if (modelLower.startsWith(key)) {
        const color = colors[key];
        if (color) return color;
      }
    }

    // Second pass: check if model contains any key
    for (const key of sortedKeys.sort((a, b) => b.length - a.length)) {
      if (modelLower.includes(key) || key.includes(modelLower)) {
        const color = colors[key];
        if (color) return color;
      }
    }
  }

  // Try backend name as fallback
  if (backendLower) {
    if (colors[backendLower]) {
      return colors[backendLower];
    }

    const sortedKeys = Object.keys(colors).filter(k => k !== 'default');

    // First pass: check if backend STARTS with any key
    for (const key of sortedKeys.sort((a, b) => b.length - a.length)) {
      if (backendLower.startsWith(key)) {
        const color = colors[key];
        if (color) return color;
      }
    }

    // Second pass: partial match on backend
    for (const key of sortedKeys.sort((a, b) => b.length - a.length)) {
      if (backendLower.includes(key)) {
        const color = colors[key];
        if (color) return color;
      }
    }
  }

  // Default fallback
  return colors['default'] || '#4ADE80';
}

/**
 * Generate CSS custom properties for a model color
 * Useful for setting multiple related colors (main, light, dark variants)
 */
export function getModelColorVars(
  model: string | undefined | null,
  backendName: string | undefined | null,
  customColors?: Record<string, string>
): Record<string, string> {
  const color = getModelColor(model, backendName, customColors);

  return {
    '--model-color': color,
    '--model-color-bg': `${color}14`,  // 8% opacity
    '--model-color-border': `${color}33`, // 20% opacity
    '--model-color-text': color,
  };
}
