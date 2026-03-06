/**
 * Color definitions for the ChatMinimap
 *
 * These colors match the exchange color scheme used in StreamingTurnsView
 */

import type { MinimapColors } from './minimapTypes';

// Exchange border colors (matching StreamingTurnsView.css)
export const EXCHANGE_COLORS = [
  '#60a5fa', // blue
  '#c084fc', // purple
  '#22d3ee', // cyan
  '#4ade80', // green
  '#facc15', // yellow
  '#f87171', // red
];

// Dark theme colors
export const MINIMAP_COLORS_DARK: MinimapColors = {
  background: 'rgba(26, 26, 26, 0.95)', // --bg-primary
  user: 'rgba(59, 130, 246, 0.8)',      // Blue
  assistant: 'rgba(34, 197, 94, 0.7)',   // Green
  tool: 'rgba(251, 146, 60, 0.7)',       // Orange
  system: 'rgba(148, 163, 184, 0.6)',    // Slate
  systemLight: 'rgba(148, 163, 184, 0.3)',
  viewport: 'rgba(59, 130, 246, 0.15)',
  viewportBorder: 'rgba(59, 130, 246, 0.5)',
  newContent: 'rgba(59, 130, 246, 0.4)',
};

// Light theme colors
export const MINIMAP_COLORS_LIGHT: MinimapColors = {
  background: 'rgba(255, 255, 255, 0.95)',
  user: 'rgba(37, 99, 235, 0.7)',        // Blue-600
  assistant: 'rgba(22, 163, 74, 0.6)',    // Green-600
  tool: 'rgba(234, 88, 12, 0.6)',         // Orange-600
  system: 'rgba(100, 116, 139, 0.5)',     // Slate-500
  systemLight: 'rgba(100, 116, 139, 0.25)',
  viewport: 'rgba(37, 99, 235, 0.1)',
  viewportBorder: 'rgba(37, 99, 235, 0.4)',
  newContent: 'rgba(37, 99, 235, 0.3)',
};

/**
 * Get the appropriate color scheme based on theme
 */
export function getMinimapColors(isDarkTheme: boolean): MinimapColors {
  return isDarkTheme ? MINIMAP_COLORS_DARK : MINIMAP_COLORS_LIGHT;
}

/**
 * Get exchange background color with alpha
 */
export function getExchangeColor(colorIndex: number, alpha: number = 0.15): string {
  const baseColor = EXCHANGE_COLORS[colorIndex % EXCHANGE_COLORS.length] ?? EXCHANGE_COLORS[0]!;
  // Convert hex to rgba
  const r = parseInt(baseColor.slice(1, 3), 16);
  const g = parseInt(baseColor.slice(3, 5), 16);
  const b = parseInt(baseColor.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
