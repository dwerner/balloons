/**
 * Calendar Plugin UI Entry Point
 *
 * Exports the main CalendarTab component and plugin manifest.
 */

import React from 'react';
import { CalendarTab, type PluginContext, type DomainEventData } from './CalendarTab';

// Plugin metadata
export const pluginId = 'calendar';
export const pluginName = 'Calendar';
export const pluginVersion = '0.1.0';

// Export types for the host app
export type { PluginContext, DomainEventData };

// The main plugin component
export { CalendarTab };
export { CalendarTab as default };

// Export sub-components for direct usage
export { MonthView } from './MonthView';
export { WeekGantt } from './WeekGantt';

// Plugin manifest for dynamic loading
export const manifest = {
  id: pluginId,
  name: pluginName,
  version: pluginVersion,
  // Tab configuration
  tab: {
    id: 'calendar',
    label: 'Calendar',
    icon: '📅',
  },
  // The main component to render
  component: CalendarTab,
};

/**
 * Plugin initialization function
 * Called by the host when the plugin is loaded
 */
export function init(context: { React: typeof React }): typeof manifest {
  console.log('[Calendar Plugin] Initializing with React', context.React.version);
  return manifest;
}

// Self-register when loaded as a script
if (typeof window !== 'undefined') {
  const plugins = (window as any).__BALLOONS_PLUGINS__;
  if (plugins && typeof plugins.register === 'function') {
    console.log('[Calendar Plugin] Auto-registering with manifest:', {
      id: manifest.id,
      name: manifest.name,
      version: manifest.version,
      hasTab: !!manifest.tab,
      hasComponent: !!manifest.component,
    });
    plugins.register('calendar', manifest);
  }
}
