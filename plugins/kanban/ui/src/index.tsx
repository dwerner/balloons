/**
 * Kanban Plugin UI Entry Point
 *
 * Exports the main KanbanTab component and plugin manifest.
 */

import React from 'react';
import { KanbanTab, type PluginContext, type DomainEventData } from './KanbanTab';

// Plugin metadata
export const pluginId = 'kanban';
export const pluginName = 'Kanban';
export const pluginVersion = '0.1.0';

// Export types for the host app
export type { PluginContext, DomainEventData };

// The main plugin component
export { KanbanTab };
export { KanbanTab as default };

// Plugin manifest for dynamic loading
export const manifest = {
  id: pluginId,
  name: pluginName,
  version: pluginVersion,
  // Tab configuration
  tab: {
    id: 'kanban',
    label: 'Kanban',
    icon: '📋',
  },
  // The main component to render
  component: KanbanTab,
};

/**
 * Plugin initialization function
 * Called by the host when the plugin is loaded
 */
export function init(context: { React: typeof React }): typeof manifest {
  console.log('[Kanban Plugin] Initializing with React', context.React.version);
  return manifest;
}

// Self-register when loaded as a script
if (typeof window !== 'undefined') {
  const plugins = (window as any).__BALLOONS_PLUGINS__;
  if (plugins && typeof plugins.register === 'function') {
    console.log('[Kanban Plugin] Auto-registering with manifest:', {
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      hasTab: !!manifest.tab,
      hasComponent: !!manifest.component,
    });
    plugins.register('kanban', manifest);
  }
}
