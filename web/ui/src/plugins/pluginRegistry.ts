/**
 * Plugin Registry
 *
 * Manages dynamic loading and lifecycle of plugin UI bundles.
 * Plugins register their React components and metadata here.
 */

import React from 'react';
import ReactDOM from 'react-dom';
import * as jsxDevRuntime from 'react/jsx-dev-runtime';

// Confirm dialog options (matches app-level DialogContext)
export interface ConfirmOptions {
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'default' | 'danger' | 'warning' | 'success';
}

// Plugin context passed to plugin components
export interface PluginContext {
  sendMessage?: (message: string) => void;
  sessionId?: string;
  subscribeToDomainEvents?: (
    domainId: string,
    callback: (event: DomainEventData) => void
  ) => () => void;
  requestDomainState?: (domainId: string) => Promise<boolean>;
  isLLMResponding?: boolean;
  /** Show a confirmation dialog, returns true if confirmed */
  confirm?: (options: ConfirmOptions) => Promise<boolean>;
  /**
   * Call a @ws_expose method on a domain plugin.
   * Use this for methods that return structured data for the UI.
   * The methodName is the camelCase wire name (e.g., "getBrowserHosts" for get_browser_hosts).
   */
  callDomainMethod?: (
    methodName: string,
    params?: Record<string, unknown> | null
  ) => Promise<Record<string, unknown>>;
}

export interface DomainEventData {
  sessionId: string;
  domainId: string;
  eventType: string;
  data: Record<string, unknown>;
}

// Plugin manifest from build
export interface PluginManifest {
  id: string;
  name: string;
  version: string;
  tab?: {
    id: string;
    label: string;
    icon: string;
  };
  component: React.ComponentType<PluginContext>;
}

// Plugin info from server
export interface PluginInfo {
  id: string;
  manifest: {
    pluginId: string;
    version: string;
    builtAt: string;
    files: {
      js: string;
      css: string | null;
    };
  };
}

// Internal plugin state
interface LoadedPlugin {
  info: PluginInfo;
  manifest: PluginManifest;
  cssElement?: HTMLLinkElement;
}

class PluginRegistryImpl {
  private plugins: Map<string, LoadedPlugin> = new Map();
  private loadingPlugins: Map<string, Promise<PluginManifest>> = new Map();
  private listeners: Set<() => void> = new Set();

  constructor() {
    // Expose React globally for plugins
    (window as any).React = React;
    (window as any).ReactDOM = ReactDOM;
    // Expose JSX runtime for plugins using the new JSX transform
    (window as any).__REACT_JSX_RUNTIME__ = jsxDevRuntime;

    // Create plugin registration point
    (window as any).__BALLOONS_PLUGINS__ = {
      register: (id: string, manifest: PluginManifest) => {
        console.log(`[PluginRegistry] Plugin registered: ${id}`, manifest);
        // Store in a temporary location for the loader to pick up
        (window as any).__BALLOONS_PLUGINS__[`__pending_${id}`] = manifest;
      },
    };
  }

  /**
   * Get list of available plugins from server
   */
  async listAvailable(): Promise<PluginInfo[]> {
    try {
      const response = await fetch('/api/plugins');
      if (!response.ok) {
        console.error('[PluginRegistry] Failed to fetch plugin list');
        return [];
      }
      return await response.json();
    } catch (error) {
      console.error('[PluginRegistry] Error fetching plugins:', error);
      return [];
    }
  }

  /**
   * Load a plugin by ID
   */
  async load(pluginId: string): Promise<PluginManifest | null> {
    // Already loaded?
    const existing = this.plugins.get(pluginId);
    if (existing) {
      return existing.manifest;
    }

    // Already loading?
    const pending = this.loadingPlugins.get(pluginId);
    if (pending) {
      return pending;
    }

    // Start loading
    const loadPromise = this._loadPlugin(pluginId);
    this.loadingPlugins.set(pluginId, loadPromise);

    try {
      const manifest = await loadPromise;
      return manifest;
    } finally {
      this.loadingPlugins.delete(pluginId);
    }
  }

  private async _loadPlugin(pluginId: string): Promise<PluginManifest> {
    console.log(`[PluginRegistry] Loading plugin: ${pluginId}`);

    // Fetch plugin info
    const infoResponse = await fetch(`/api/plugins/${pluginId}/manifest.json`);
    if (!infoResponse.ok) {
      throw new Error(`Plugin not found: ${pluginId}`);
    }
    const info: PluginInfo['manifest'] = await infoResponse.json();

    // Load CSS if present
    let cssElement: HTMLLinkElement | undefined;
    if (info.files.css) {
      cssElement = document.createElement('link');
      cssElement.rel = 'stylesheet';
      cssElement.href = `/api/plugins/${pluginId}/${info.files.css}`;
      cssElement.dataset.plugin = pluginId;
      document.head.appendChild(cssElement);
    }

    // Load JS bundle
    const script = document.createElement('script');
    script.src = `/api/plugins/${pluginId}/${info.files.js}`;
    script.dataset.plugin = pluginId;

    // Wait for script to load and plugin to register
    await new Promise<void>((resolve, reject) => {
      script.onload = () => {
        // Give the IIFE time to execute
        setTimeout(resolve, 10);
      };
      script.onerror = () => reject(new Error(`Failed to load plugin script: ${pluginId}`));
      document.head.appendChild(script);
    });

    // Get registered manifest
    const manifest = (window as any).__BALLOONS_PLUGINS__[`__pending_${pluginId}`];
    if (!manifest) {
      throw new Error(`Plugin did not register: ${pluginId}`);
    }

    // Clean up temporary storage
    delete (window as any).__BALLOONS_PLUGINS__[`__pending_${pluginId}`];

    // Store loaded plugin
    this.plugins.set(pluginId, {
      info: { id: pluginId, manifest: info },
      manifest,
      cssElement,
    });

    this._notifyListeners();
    console.log(`[PluginRegistry] Plugin loaded: ${pluginId}`);

    return manifest;
  }

  /**
   * Unload a plugin
   */
  unload(pluginId: string): void {
    const plugin = this.plugins.get(pluginId);
    if (!plugin) {
      return;
    }

    console.log(`[PluginRegistry] Unloading plugin: ${pluginId}`);

    // Remove CSS
    if (plugin.cssElement) {
      plugin.cssElement.remove();
    }

    // Remove script (optional - scripts can't really be unloaded)
    const script = document.querySelector(`script[data-plugin="${pluginId}"]`);
    if (script) {
      script.remove();
    }

    this.plugins.delete(pluginId);
    this._notifyListeners();
  }

  /**
   * Get a loaded plugin's manifest
   */
  get(pluginId: string): PluginManifest | undefined {
    return this.plugins.get(pluginId)?.manifest;
  }

  /**
   * Get all loaded plugins
   */
  getLoaded(): PluginManifest[] {
    return Array.from(this.plugins.values()).map(p => p.manifest);
  }

  /**
   * Check if a plugin is loaded
   */
  isLoaded(pluginId: string): boolean {
    return this.plugins.has(pluginId);
  }

  /**
   * Get the builtAt timestamp for a loaded plugin
   */
  getLoadedBuiltAt(pluginId: string): string | undefined {
    return this.plugins.get(pluginId)?.info.manifest.builtAt;
  }

  /**
   * Check if a newer build is available for a loaded plugin
   */
  async hasUpdate(pluginId: string): Promise<boolean> {
    const loaded = this.plugins.get(pluginId);
    if (!loaded) return false;

    try {
      const response = await fetch(`/api/plugins/${pluginId}/manifest.json`);
      if (!response.ok) return false;
      const manifest = await response.json();

      const loadedAt = loaded.info.manifest.builtAt;
      const availableAt = manifest.builtAt;

      if (loadedAt && availableAt) {
        return new Date(availableAt) > new Date(loadedAt);
      }
    } catch {
      return false;
    }
    return false;
  }

  /**
   * Subscribe to plugin changes
   */
  subscribe(callback: () => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  private _notifyListeners(): void {
    this.listeners.forEach(cb => cb());
  }
}

// Singleton instance
export const pluginRegistry = new PluginRegistryImpl();

// React hook for plugin state
export function usePlugins() {
  const [, forceUpdate] = React.useReducer(x => x + 1, 0);

  React.useEffect(() => {
    return pluginRegistry.subscribe(forceUpdate);
  }, []);

  return {
    loaded: pluginRegistry.getLoaded(),
    load: (id: string) => pluginRegistry.load(id),
    unload: (id: string) => pluginRegistry.unload(id),
    isLoaded: (id: string) => pluginRegistry.isLoaded(id),
  };
}
