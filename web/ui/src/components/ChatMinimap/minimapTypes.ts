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
export interface MinimapEditBlock {
  id: string;
  turnId: string;
  top: number;      // Relative to exchange top in rendered pixels
  height: number;   // Rendered height in pixels
  filePath?: string;
}

export interface ExchangeDOMRect {
  id: string;
  colorIndex: number;
  top: number;      // Relative to scroll container's scrollTop=0
  height: number;   // Rendered height in pixels
  turnRange?: string;  // e.g., "#0-5" or "#12"
  tokenCount?: number; // Total tokens in this exchange
  turnIndices?: number[]; // Turn indices for archive action
  turnIds?: string[]; // Turn IDs for stable tracking during archive
  editBlocks?: MinimapEditBlock[];
}

// Calculated layout positions
export interface MinimapTurnLayout {
  turn: MinimapTurn;
  y: number;        // Relative to exchange top
  height: number;
  x: number;        // 0-1 normalized, for parallel turns
  width: number;    // 0-1 normalized
}

export interface MinimapEditBlockLayout {
  block: MinimapEditBlock;
  y: number;      // Relative to exchange top in minimap pixels
  height: number;
}

export interface MinimapExchangeLayout {
  exchange: MinimapExchange;
  y: number;
  height: number;
  turns: MinimapTurnLayout[];
  editBlocks?: MinimapEditBlockLayout[];
  turnRange?: string;  // e.g., "#0-5" for labeling in the minimap
  tokenCount?: number; // Total tokens in this exchange
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
  editBlock: string;
  editBlockHover: string;
  viewport: string;
  viewportBorder: string;
  newContent: string;
}

export interface MinimapRenderOptions {
  colors: MinimapColors;
  showViewport: boolean;
  newContentFromY?: number; // Y position where new content starts
  hoveredExchangeId?: string; // Exchange to highlight on hover
  hoveredEditBlockId?: string; // Edit block to highlight on hover
  selectedExchangeId?: string; // Exchange that's currently selected/active
  archivingExchangeIds?: Set<string>; // Exchanges currently being archived
}

/**
 * Context menu action for an exchange
 */
export interface ExchangeContextMenuAction {
  type: 'archive' | 'jump';
  exchangeId: string;
  turnRange?: string;  // e.g., "#0-5"
  tokenCount?: number;
}
