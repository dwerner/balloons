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
  const { colors, showViewport, newContentFromY, hoveredExchangeId, hoveredEditBlockId, selectedExchangeId, archivingExchangeIds } = options;

  // Clear canvas
  ctx.fillStyle = colors.background;
  ctx.fillRect(0, 0, width, height);

  if (layout.exchanges.length === 0) {
    return;
  }

  const contentWidth = width - CONTENT_PADDING_X * 2 - EXCHANGE_BORDER_WIDTH;
  const contentX = CONTENT_PADDING_X + EXCHANGE_BORDER_WIDTH;

  const contentOffsetY = layout.contentOffsetY ?? 0;

  // Draw each exchange
  for (const exLayout of layout.exchanges) {
    const renderY = exLayout.y - contentOffsetY;
    const { exchange, height: exHeight, turns } = exLayout;

    if (renderY + exHeight < 0 || renderY > height) {
      continue;
    }
    const isHovered = exchange.id === hoveredExchangeId;
    const isSelected = exchange.id === selectedExchangeId;
    const isArchiving = archivingExchangeIds?.has(exchange.id) ?? false;

    // Exchange background (subtle tint based on color index, brighter if hovered/selected)
    // Archiving exchanges get a pulsing amber tint
    const bgAlpha = isArchiving ? 0.25 : isHovered ? 0.2 : isSelected ? 0.15 : 0.08;
    const bgColor = isArchiving
      ? 'rgba(245, 158, 11, 0.3)'  // Amber for archiving
      : getExchangeColor(exchange.colorIndex, bgAlpha);
    ctx.fillStyle = bgColor;
    ctx.fillRect(CONTENT_PADDING_X, renderY, width - CONTENT_PADDING_X * 2, exHeight);

    // Hover/selection outline
    if (isHovered || isSelected) {
      ctx.strokeStyle = isHovered
        ? 'rgba(255, 255, 255, 0.4)'
        : 'rgba(59, 130, 246, 0.5)';
      ctx.lineWidth = isHovered ? 2 : 1;
      ctx.strokeRect(
        CONTENT_PADDING_X + 0.5,
        renderY + 0.5,
        width - CONTENT_PADDING_X * 2 - 1,
        exHeight - 1
      );
    }

    // Exchange left border (stronger color, even stronger if hovered, amber if archiving)
    const borderColor = isArchiving
      ? 'rgb(245, 158, 11)'  // Amber for archiving
      : EXCHANGE_COLORS[exchange.colorIndex % EXCHANGE_COLORS.length] ?? EXCHANGE_COLORS[0]!;
    ctx.fillStyle = borderColor;
    ctx.fillRect(CONTENT_PADDING_X, renderY, isHovered ? EXCHANGE_BORDER_WIDTH + 1 : EXCHANGE_BORDER_WIDTH, exHeight);

    // Archiving indicator: pulsing outline
    if (isArchiving) {
      ctx.strokeStyle = 'rgba(245, 158, 11, 0.8)';
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 2]);  // Dashed line for "in progress" feel
      ctx.strokeRect(
        CONTENT_PADDING_X + 0.5,
        renderY + 0.5,
        width - CONTENT_PADDING_X * 2 - 1,
        exHeight - 1
      );
      ctx.setLineDash([]);  // Reset
    }

    // Check if we have individual turn layouts or just a solid exchange block
    if (turns && turns.length > 0) {
      // Draw individual turns (legacy token-based layout)
      for (const turnLayout of turns) {
        const turnY = renderY + EXCHANGE_PADDING_Y + turnLayout.y;
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
      const fillY = renderY + EXCHANGE_PADDING_Y;
      const fillH = Math.max(exHeight - EXCHANGE_PADDING_Y * 2, 1);

      ctx.fillStyle = colors.assistant;
      ctx.globalAlpha = 0.5;
      ctx.fillRect(contentX, fillY, contentWidth, fillH);
      ctx.globalAlpha = 1.0;

      // Draw token count centered in the exchange if tall enough
      if (exLayout.tokenCount !== undefined && exLayout.tokenCount > 0 && exHeight >= 12) {
        ctx.save();
        ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';

        // Use larger font, scale with exchange height
        const fontSize = exHeight >= 24 ? 11 : exHeight >= 16 ? 9 : 8;
        ctx.font = `bold ${fontSize}px monospace`;
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'center';

        // Format token count (compact: 1.2k, 15k, etc.)
        let tokenLabel: string;
        if (exLayout.tokenCount >= 10000) {
          tokenLabel = `${Math.round(exLayout.tokenCount / 1000)}k`;
        } else if (exLayout.tokenCount >= 1000) {
          tokenLabel = `${(exLayout.tokenCount / 1000).toFixed(1)}k`;
        } else {
          tokenLabel = String(exLayout.tokenCount);
        }

        // Draw centered in the exchange
        const labelX = CONTENT_PADDING_X + (width - CONTENT_PADDING_X * 2) / 2;
        const labelY = renderY + exHeight / 2;

        ctx.fillText(tokenLabel, labelX, labelY);
        ctx.restore();
      }
    }

    if (exLayout.editBlocks && exLayout.editBlocks.length > 0) {
      for (const editLayout of exLayout.editBlocks) {
        const editY = renderY + editLayout.y;
        const editHeight = Math.max(editLayout.height, 3);
        const isHoveredEdit = editLayout.block.id === hoveredEditBlockId;

        ctx.save();
        ctx.fillStyle = isHoveredEdit ? colors.editBlockHover : colors.editBlock;
        ctx.fillRect(contentX, editY, contentWidth, editHeight);
        ctx.strokeStyle = isHoveredEdit ? 'rgba(255, 255, 255, 0.9)' : 'rgba(255, 255, 255, 0.5)';
        ctx.lineWidth = isHoveredEdit ? 1.5 : 1;
        ctx.strokeRect(contentX + 0.5, editY + 0.5, contentWidth - 1, Math.max(editHeight - 1, 1));
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
  const visibleNewContentY = newContentFromY !== undefined
    ? newContentFromY - (layout.contentOffsetY ?? 0)
    : undefined;

  if (visibleNewContentY !== undefined && visibleNewContentY < height && visibleNewContentY > -25) {
    // Gradient glow starting at newContentFromY
    const glowHeight = 20;
    const gradient = ctx.createLinearGradient(0, visibleNewContentY - 5, 0, visibleNewContentY + glowHeight);
    gradient.addColorStop(0, 'rgba(59, 130, 246, 0)');
    gradient.addColorStop(0.3, colors.newContent);
    gradient.addColorStop(1, 'rgba(59, 130, 246, 0)');

    ctx.fillStyle = gradient;
    ctx.fillRect(0, visibleNewContentY - 5, width, glowHeight + 5);

    // Small indicator line
    ctx.strokeStyle = colors.newContent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, visibleNewContentY);
    ctx.lineTo(width, visibleNewContentY);
    ctx.stroke();
  }
}
