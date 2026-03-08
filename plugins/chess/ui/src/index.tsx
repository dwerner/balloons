/**
 * Chess Plugin UI Entry Point
 *
 * This file is the entry point for the plugin's UI bundle.
 * It exports everything needed by the host application to render
 * the plugin's UI components.
 */

import React from 'react';
import { ChessTab, type PluginContext, type DomainEventData } from './ChessTab';

// Plugin metadata
export const pluginId = 'chess';
export const pluginName = 'Chess';
export const pluginVersion = '0.1.0';

// Export types for the host app
export type { PluginContext, DomainEventData };

// The main plugin component
export { ChessTab };
export { ChessTab as default };

// Plugin manifest for dynamic loading
export const manifest = {
  id: pluginId,
  name: pluginName,
  version: pluginVersion,
  // Tab configuration
  tab: {
    id: 'chess',
    label: 'Chess',
    icon: '♟',
  },
  // The main component to render
  component: ChessTab,
};

/**
 * Plugin initialization function
 * Called by the host when the plugin is loaded
 */
export function init(context: { React: typeof React }): typeof manifest {
  // Verify React version compatibility
  console.log('[Chess Plugin] Initializing with React', context.React.version);
  return manifest;
}

// Self-register when loaded as a script
if (typeof window !== 'undefined') {
  const plugins = (window as any).__BALLOONS_PLUGINS__;
  if (plugins && typeof plugins.register === 'function') {
    console.log('[Chess Plugin] Auto-registering');
    plugins.register('chess', manifest);
  }
}
