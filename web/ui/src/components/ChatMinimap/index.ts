/**
 * ChatMinimap - Visual overview component for conversation navigation
 */

import { ChatMinimap } from './ChatMinimap';
export { ChatMinimap, type ChatMinimapProps } from './ChatMinimap';
export type {
  MinimapExchange,
  MinimapTurn,
  MinimapLayout,
  ExchangeDOMRect,
  ExchangeContextMenuAction,
  MinimapJumpBlock,
} from './minimapTypes';
export { getMinimapColors, EXCHANGE_COLORS } from './minimapColors';

export default ChatMinimap;
