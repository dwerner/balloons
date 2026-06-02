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

function yClamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, max));
}

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
  viewportHeight: number,
  zoom: number = 1,
  zoomAnchorScrollTop?: number,
  zoomAnchorCanvasY?: number,
  manualContentOffsetY?: number
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

  // Scale factor: minimap pixels per scroll pixel
  const baseScale = canvasHeight / scrollHeight;
  const scale = baseScale * zoom;
  const totalHeight = scrollHeight * scale;

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
      jumpBlocks: rect.jumpBlocks?.map((block) => ({
        block,
        y: block.top * scale,
        height: Math.max(block.height * scale, MIN_EXCHANGE_HEIGHT),
      })) ?? [],
      turnRange: rect.turnRange,
      tokenCount: rect.tokenCount,
    });
  }

  // Viewport position within virtual minimap content
  const viewportHeightScaled = Math.max(viewportHeight * scale, 10);
  const anchorScrollTop = yClamp(zoomAnchorScrollTop ?? (scrollTop + viewportHeight / 2), 0, Math.max(scrollHeight, 0));
  const anchorCanvasY = yClamp(zoomAnchorCanvasY ?? (canvasHeight / 2), 0, canvasHeight);
  const anchorContentY = anchorScrollTop * scale;
  let contentOffsetY = manualContentOffsetY ?? (anchorContentY - anchorCanvasY);
  const maxOffsetY = Math.max(0, totalHeight - canvasHeight);
  contentOffsetY = Math.max(0, Math.min(contentOffsetY, maxOffsetY));
  const viewportTop = scrollTop * scale - contentOffsetY;

  return {
    exchanges: exchangeLayouts,
    totalHeight,
    viewportTop,
    viewportHeight: viewportHeightScaled,
    scale,
    contentOffsetY,
    anchorCanvasY,
    maxContentOffsetY: maxOffsetY,
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
  const contentY = y + (layout.contentOffsetY ?? 0);
  for (const exLayout of layout.exchanges) {
    if (contentY >= exLayout.y && contentY < exLayout.y + exLayout.height) {
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

  // Convert canvas Y into virtual minimap content Y, then to scroll position
  const contentY = y + (layout.contentOffsetY ?? 0);
  const scrollTop = contentY / layout.scale;

  // Clamp to valid scroll range
  const maxScroll = scrollHeight - viewportHeight;
  return Math.max(0, Math.min(scrollTop, maxScroll));
}
