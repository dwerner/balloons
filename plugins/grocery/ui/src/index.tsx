/**
 * Grocery Plugin UI Entry Point
 */

import React from 'react';
import { GroceryTab, type PluginContext, type DomainEventData } from './GroceryTab';

// Plugin metadata
export const pluginId = 'grocery';
export const pluginName = 'Grocery';
export const pluginVersion = '0.1.0';

// Export types for the host app
export type { PluginContext, DomainEventData };

// The main plugin component
export { GroceryTab };
export { GroceryTab as default };

// Plugin manifest for dynamic loading
export const manifest = {
  id: pluginId,
  name: pluginName,
  version: pluginVersion,
  tab: {
    id: 'grocery',
    label: 'Grocery',
    icon: '🛒',
  },
  component: GroceryTab,
};

/**
 * Plugin initialization function
 */
export function init(context: { React: typeof React }): typeof manifest {
  console.log('[Grocery Plugin] Initializing with React', context.React.version);
  return manifest;
}

// Self-register when loaded as a script
if (typeof window !== 'undefined') {
  const plugins = (window as any).__BALLOONS_PLUGINS__;
  if (plugins && typeof plugins.register === 'function') {
    console.log('[Grocery Plugin] Auto-registering');
    plugins.register('grocery', manifest);
  }
}
