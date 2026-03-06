/**
 * Layout calculation for the ChatMinimap
 *
 * Uses actual DOM measurements to create a proportionally accurate minimap.
 * The minimap is a true scaled representation of the scroll container.
 */

import type {
  MinimapExchange,
  MinimapLayout,
  MinimapExchangeLayout,
  ExchangeDOMRect,
} from './minimapTypes';

// Layout constants
const MIN_EXCHANGE_HEIGHT = 3;  // Minimum height for visibility in minimap

/**
 * Calculate minimap layout from DOM-measured exchange positions
 *
 * This creates a true 1:1 proportional map of the scroll container.
 * The minimap is scaled down from scrollHeight to canvasHeight.
 */
export function calculateMinimapLayoutFromDOM(
  exchangeRects: ExchangeDOMRect[],
  canvasHeight: number,
  scrollTop: number,
  scrollHeight: number,
  viewportHeight: number
): MinimapLayout {
  if (exchangeRects.length === 0 || canvasHeight <= 0 || scrollHeight <= 0) {
    return {
      exchanges: [],
      totalHeight: 0,
      viewportTop: 0,
      viewportHeight: canvasHeight,
      scale: 1,
    };
  }

  // Scale factor: canvas pixels per scroll pixel
  const scale = canvasHeight / scrollHeight;

  const exchangeLayouts: MinimapExchangeLayout[] = [];

  for (const rect of exchangeRects) {
    // Scale DOM position to minimap position
    const y = rect.top * scale;
    const height = Math.max(rect.height * scale, MIN_EXCHANGE_HEIGHT);

    exchangeLayouts.push({
      exchange: {
        id: rect.id,
        colorIndex: rect.colorIndex,
        turns: [], // We don't need individual turn layout for DOM-based approach
      },
      y,
      height,
      turns: [], // Individual turns rendered as a block
    });
  }

  // Viewport position - simple scale since we're using scroll coordinates directly
  const viewportTop = scrollTop * scale;
  const viewportHeightScaled = Math.max(viewportHeight * scale, 10);

  return {
    exchanges: exchangeLayouts,
    totalHeight: canvasHeight,
    viewportTop,
    viewportHeight: viewportHeightScaled,
    scale,
  };
}

/**
 * Legacy token-based layout calculation - kept for backwards compatibility
 * @deprecated Use calculateMinimapLayoutFromDOM instead
 */
export function calculateMinimapLayout(
  exchanges: MinimapExchange[],
  canvasHeight: number,
  scrollTop: number,
  scrollHeight: number,
  viewportHeight: number
): MinimapLayout {
  if (exchanges.length === 0 || canvasHeight <= 0 || scrollHeight <= 0) {
    return {
      exchanges: [],
      totalHeight: 0,
      viewportTop: 0,
      viewportHeight: canvasHeight,
      scale: 1,
    };
  }

  const scale = canvasHeight / scrollHeight;
  const viewportTop = scrollTop * scale;
  const viewportHeightScaled = Math.max(viewportHeight * scale, 10);

  // Simple equal distribution as fallback
  const exchangeHeight = canvasHeight / exchanges.length;
  const exchangeLayouts: MinimapExchangeLayout[] = exchanges.map((exchange, i) => ({
    exchange,
    y: i * exchangeHeight,
    height: exchangeHeight,
    turns: [],
  }));

  return {
    exchanges: exchangeLayouts,
    totalHeight: canvasHeight,
    viewportTop,
    viewportHeight: viewportHeightScaled,
    scale,
  };
}

/**
 * Find which exchange is at a given Y position in the minimap
 */
export function findExchangeAtPosition(
  layout: MinimapLayout,
  y: number
): MinimapExchangeLayout | null {
  for (const exLayout of layout.exchanges) {
    if (y >= exLayout.y && y < exLayout.y + exLayout.height) {
      return exLayout;
    }
  }
  return null;
}

/**
 * Convert a minimap Y position to a scroll position
 */
export function minimapYToScrollPosition(
  layout: MinimapLayout,
  y: number,
  scrollHeight: number,
  viewportHeight: number
): number {
  if (layout.scale <= 0) return 0;

  // Direct scale conversion - minimap is proportional to scroll
  const scrollTop = y / layout.scale;

  // Clamp to valid scroll range
  const maxScroll = scrollHeight - viewportHeight;
  return Math.max(0, Math.min(scrollTop, maxScroll));
}
