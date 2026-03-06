/**
 * Canvas rendering for the ChatMinimap
 *
 * Draws exchanges, turns, viewport indicator, and new content highlight.
 */

import type {
  MinimapLayout,
  MinimapTurn,
  MinimapColors,
  MinimapRenderOptions,
} from './minimapTypes';
import { EXCHANGE_COLORS, getExchangeColor } from './minimapColors';

// Rendering constants
const CONTENT_PADDING_X = 2;  // Pixels on left/right
const EXCHANGE_BORDER_WIDTH = 2;
const EXCHANGE_PADDING_Y = 1;

/**
 * Get the fill color for a turn based on its role and content type
 */
function getTurnColor(turn: MinimapTurn, colors: MinimapColors): string {
  // Special content types
  if (turn.contentType === 'fork' || turn.contentType === 'merge' || turn.contentType === 'merged_to') {
    return colors.system;
  }
  if (turn.contentType === 'archive') {
    return colors.systemLight;
  }

  // Role-based colors
  switch (turn.role) {
    case 'user':
      return colors.user;
    case 'assistant':
      return colors.assistant;
    case 'tool':
      return colors.tool;
    case 'system':
      return colors.systemLight;
    default:
      return colors.systemLight;
  }
}

/**
 * Draw a small icon indicator for special turn types
 */
function drawSpecialIndicator(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  contentType: string
): void {
  if (height < 4 || width < 4) return; // Too small for icons

  const centerX = x + width / 2;
  const centerY = y + height / 2;
  const size = Math.min(width, height, 8) * 0.6;

  ctx.save();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
  ctx.lineWidth = 1;

  if (contentType === 'fork') {
    // Fork icon: Y shape
    ctx.beginPath();
    ctx.moveTo(centerX, centerY + size / 2);
    ctx.lineTo(centerX, centerY);
    ctx.lineTo(centerX - size / 2, centerY - size / 2);
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(centerX + size / 2, centerY - size / 2);
    ctx.stroke();
  } else if (contentType === 'merge' || contentType === 'merged_to') {
    // Merge icon: inverted Y shape
    ctx.beginPath();
    ctx.moveTo(centerX, centerY - size / 2);
    ctx.lineTo(centerX, centerY);
    ctx.lineTo(centerX - size / 2, centerY + size / 2);
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(centerX + size / 2, centerY + size / 2);
    ctx.stroke();
  }

  ctx.restore();
}

/**
 * Main render function for the minimap
 */
export function renderMinimap(
  ctx: CanvasRenderingContext2D,
  layout: MinimapLayout,
  width: number,
  height: number,
  options: MinimapRenderOptions
): void {
  const { colors, showViewport, newContentFromY } = options;

  // Clear canvas
  ctx.fillStyle = colors.background;
  ctx.fillRect(0, 0, width, height);

  if (layout.exchanges.length === 0) {
    return;
  }

  const contentWidth = width - CONTENT_PADDING_X * 2 - EXCHANGE_BORDER_WIDTH;
  const contentX = CONTENT_PADDING_X + EXCHANGE_BORDER_WIDTH;

  // Draw each exchange
  for (const exLayout of layout.exchanges) {
    const { exchange, y, height: exHeight, turns } = exLayout;

    // Exchange background (subtle tint based on color index)
    const bgColor = getExchangeColor(exchange.colorIndex, 0.08);
    ctx.fillStyle = bgColor;
    ctx.fillRect(CONTENT_PADDING_X, y, width - CONTENT_PADDING_X * 2, exHeight);

    // Exchange left border (stronger color)
    const borderColor = EXCHANGE_COLORS[exchange.colorIndex % EXCHANGE_COLORS.length] ?? EXCHANGE_COLORS[0]!;
    ctx.fillStyle = borderColor;
    ctx.fillRect(CONTENT_PADDING_X, y, EXCHANGE_BORDER_WIDTH, exHeight);

    // Check if we have individual turn layouts or just a solid exchange block
    if (turns && turns.length > 0) {
      // Draw individual turns (legacy token-based layout)
      for (const turnLayout of turns) {
        const turnY = y + EXCHANGE_PADDING_Y + turnLayout.y;
        const turnX = contentX + turnLayout.x * contentWidth;
        const turnW = Math.max(turnLayout.width * contentWidth, 1);
        const turnH = Math.max(turnLayout.height, 1);

        // Turn fill
        ctx.fillStyle = getTurnColor(turnLayout.turn, colors);
        ctx.fillRect(turnX, turnY, turnW, turnH);

        // Special indicators for fork/merge
        if (turnLayout.turn.contentType === 'fork' ||
            turnLayout.turn.contentType === 'merge' ||
            turnLayout.turn.contentType === 'merged_to') {
          drawSpecialIndicator(ctx, turnX, turnY, turnW, turnH, turnLayout.turn.contentType);
        }
      }
    } else {
      // DOM-based layout - fill the exchange block with a gradient or solid color
      // Use a subtle gradient from assistant color to show content
      const fillY = y + EXCHANGE_PADDING_Y;
      const fillH = Math.max(exHeight - EXCHANGE_PADDING_Y * 2, 1);

      ctx.fillStyle = colors.assistant;
      ctx.globalAlpha = 0.5;
      ctx.fillRect(contentX, fillY, contentWidth, fillH);
      ctx.globalAlpha = 1.0;

      // Draw turn range label if exchange is tall enough (at least 10px)
      if (exLayout.turnRange && exHeight >= 10) {
        ctx.save();
        ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
        ctx.font = '7px monospace';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'center';

        // Draw label centered in the exchange
        const labelX = CONTENT_PADDING_X + (width - CONTENT_PADDING_X * 2) / 2;
        const labelY = y + exHeight / 2;

        // Shorten label if needed (use just the first number for very small spaces)
        let label = exLayout.turnRange;
        if (exHeight < 14 && label.includes('-')) {
          // Just show first number for very small blocks
          label = label.split('-')[0] || label;
        }

        ctx.fillText(label, labelX, labelY);
        ctx.restore();
      }
    }
  }

  // Viewport indicator
  if (showViewport) {
    // Viewport fill
    ctx.fillStyle = colors.viewport;
    ctx.fillRect(0, layout.viewportTop, width, layout.viewportHeight);

    // Viewport border
    ctx.strokeStyle = colors.viewportBorder;
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, layout.viewportTop + 0.5, width - 1, layout.viewportHeight - 1);
  }

  // "New content" highlight when scrolled away
  if (newContentFromY !== undefined && newContentFromY < height) {
    // Gradient glow starting at newContentFromY
    const glowHeight = 20;
    const gradient = ctx.createLinearGradient(0, newContentFromY - 5, 0, newContentFromY + glowHeight);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0)');
    gradient.addColorStop(0.3, colors.newContent);
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');

    ctx.fillStyle = gradient;
    ctx.fillRect(0, newContentFromY - 5, width, glowHeight + 5);

    // Small indicator line
    ctx.strokeStyle = colors.newContent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, newContentFromY);
    ctx.lineTo(width, newContentFromY);
    ctx.stroke();
  }
}
