/**
 * Type definitions for the ChatMinimap component
 */

export interface MinimapTurn {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  contentType: string; // 'text' | 'tool_use' | 'tool_result' | 'fork' | 'merge' | 'archive' | etc
  tokens: number;
  parallelGroupId?: string;
}

export interface MinimapExchange {
  id: string;
  colorIndex: number;
  turns: MinimapTurn[];
}

/**
 * DOM-measured exchange position - actual rendered positions from the DOM
 */
export interface ExchangeDOMRect {
  id: string;
  colorIndex: number;
  top: number;      // Relative to scroll container's scrollTop=0
  height: number;   // Rendered height in pixels
  turnRange?: string;  // e.g., "#0-5" or "#12"
}

// Calculated layout positions
export interface MinimapTurnLayout {
  turn: MinimapTurn;
  y: number;        // Relative to exchange top
  height: number;
  x: number;        // 0-1 normalized, for parallel turns
  width: number;    // 0-1 normalized
}

export interface MinimapExchangeLayout {
  exchange: MinimapExchange;
  y: number;
  height: number;
  turns: MinimapTurnLayout[];
  turnRange?: string;  // e.g., "#0-5" for labeling in the minimap
}

export interface MinimapLayout {
  exchanges: MinimapExchangeLayout[];
  totalHeight: number;
  viewportTop: number;
  viewportHeight: number;
  scale: number; // scrollHeight -> canvasHeight mapping
}

export interface MinimapColors {
  background: string;
  user: string;
  assistant: string;
  tool: string;
  system: string;
  systemLight: string;
  viewport: string;
  viewportBorder: string;
  newContent: string;
}

export interface MinimapRenderOptions {
  colors: MinimapColors;
  showViewport: boolean;
  newContentFromY?: number; // Y position where new content starts
}
