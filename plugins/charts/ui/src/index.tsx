/**
 * Charts Plugin UI Entry Point
 *
 * This file is the entry point for the plugin's UI bundle.
 * It exports everything needed by the host application to render
 * the plugin's UI components.
 */

import React from 'react';
import { ChartsTab, type PluginContext, type DomainEventData } from './ChartsTab';

// Plugin metadata
export const pluginId = 'charts';
export const pluginName = 'Charts';
export const pluginVersion = '0.1.0';

// Export types for the host app
export type { PluginContext, DomainEventData };

// The main plugin component
export { ChartsTab };
export { ChartsTab as default };

// Also export sub-components for direct usage
export { ChartView } from './ChartView';

// Plugin manifest for dynamic loading
export const manifest = {
  id: pluginId,
  name: pluginName,
  version: pluginVersion,
  // Tab configuration
  tab: {
    id: 'charts',
    label: 'Charts',
    icon: '📊',
  },
  // The main component to render
  component: ChartsTab,
};

/**
 * Plugin initialization function
 * Called by the host when the plugin is loaded
 */
export function init(context: { React: typeof React }): typeof manifest {
  // Verify React version compatibility
  console.log('[Charts Plugin] Initializing with React', context.React.version);
  return manifest;
}

// Self-register when loaded as a script
if (typeof window !== 'undefined') {
  const plugins = (window as any).__BALLOONS_PLUGINS__;
  if (plugins && typeof plugins.register === 'function') {
    console.log('[Charts Plugin] Auto-registering with manifest:', {
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      hasTab: !!manifest.tab,
      hasComponent: !!manifest.component,
    });
    plugins.register('charts', manifest);
  }
}
