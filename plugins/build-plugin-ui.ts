#!/usr/bin/env bun
/**
 * Plugin UI Build Script
 *
 * Builds plugin UI bundles that can be dynamically loaded by the host app.
 * Each plugin gets its own bundle with:
 * - All its React components
 * - Inlined CSS
 * - No React dependency (uses host app's React)
 *
 * Usage:
 *   bun run build-plugin-ui.ts                    # Build all plugins
 *   bun run build-plugin-ui.ts chess              # Build specific plugin
 *   bun run build-plugin-ui.ts --watch            # Watch mode
 */

import { join, dirname, basename } from "path";
import { existsSync, mkdirSync, readdirSync, statSync } from "fs";

const pluginsDir = import.meta.dir;
const outputDir = join(pluginsDir, "dist");
const webUiDir = join(dirname(pluginsDir), "web", "ui");
const nodeModulesDir = join(webUiDir, "node_modules");

interface PluginBuildResult {
  pluginId: string;
  success: boolean;
  outputPath?: string;
  error?: string;
  js?: string;
  css?: string;
}

interface PluginPackageJson {
  name?: string;
  version?: string;
  private?: boolean;
}

/**
 * Find all plugins with UI directories
 */
function findPluginsWithUI(): string[] {
  const plugins: string[] = [];

  for (const entry of readdirSync(pluginsDir)) {
    const pluginPath = join(pluginsDir, entry);
    const uiPath = join(pluginPath, "ui", "src");

    if (statSync(pluginPath).isDirectory() && existsSync(uiPath)) {
      // Check for an entry point
      const hasEntry = existsSync(join(uiPath, "index.tsx")) ||
                       existsSync(join(uiPath, "index.ts"));
      if (hasEntry) {
        plugins.push(entry);
      }
    }
  }

  return plugins;
}

function getPluginVersion(pluginId: string): string {
  const packageJsonPath = join(pluginsDir, pluginId, "ui", "package.json");
  if (!existsSync(packageJsonPath)) {
    return "0.1.0";
  }

  try {
    const packageJsonText = require("fs").readFileSync(packageJsonPath, "utf-8");
    const packageJson = JSON.parse(packageJsonText) as PluginPackageJson;
    return packageJson.version || "0.1.0";
  } catch {
    return "0.1.0";
  }
}

/**
 * Build a single plugin's UI
 */
async function buildPlugin(pluginId: string): Promise<PluginBuildResult> {
  const srcDir = join(pluginsDir, pluginId, "ui", "src");
  const entrypoint = existsSync(join(srcDir, "index.tsx"))
    ? join(srcDir, "index.tsx")
    : join(srcDir, "index.ts");

  if (!existsSync(entrypoint)) {
    return {
      pluginId,
      success: false,
      error: `Entry point not found: ${entrypoint}`,
    };
  }

  console.log(`[Build] Building plugin: ${pluginId}`);
  console.log(`        Entry: ${entrypoint}`);

  try {
    const pluginVersion = getPluginVersion(pluginId);

    // Change to web/ui directory to resolve React from its node_modules
    const originalDir = process.cwd();
    process.chdir(webUiDir);

    // Plugin to replace React imports with global references
    const reactGlobalPlugin = {
      name: "react-global",
      setup(build: any) {
        // Redirect react imports to a virtual module that exports globals
        build.onResolve({ filter: /^react$/ }, () => ({
          path: "react",
          namespace: "react-global",
        }));
        build.onResolve({ filter: /^react\/jsx-runtime$/ }, () => ({
          path: "react/jsx-runtime",
          namespace: "react-global",
        }));
        build.onResolve({ filter: /^react\/jsx-dev-runtime$/ }, () => ({
          path: "react/jsx-dev-runtime",
          namespace: "react-global",
        }));
        build.onResolve({ filter: /^react-dom$/ }, () => ({
          path: "react-dom",
          namespace: "react-global",
        }));

        // Provide the virtual modules that use globals
        build.onLoad({ filter: /.*/, namespace: "react-global" }, (args: any) => {
          if (args.path === "react") {
            return {
              contents: `
                const React = window.React;
                export default React;
                export const {
                  useState, useEffect, useCallback, useMemo, useRef,
                  useReducer, useContext, useLayoutEffect, useImperativeHandle,
                  useSyncExternalStore, useTransition, useDeferredValue, useId,
                  memo, forwardRef, createContext, createElement, Fragment,
                  Children, cloneElement, isValidElement, lazy, Suspense,
                  startTransition, Component, PureComponent,
                } = React;
              `,
              loader: "js",
            };
          }
          if (args.path === "react/jsx-runtime" || args.path === "react/jsx-dev-runtime") {
            // React 19's jsx runtime is available as a separate export on window.React
            // We need to use the actual jsx functions, not createElement
            return {
              contents: `
                // Get the jsx runtime from window - the host app needs to expose this
                const jsxRuntime = window.__REACT_JSX_RUNTIME__ || {
                  jsx: window.React.createElement,
                  jsxs: window.React.createElement,
                  jsxDEV: window.React.createElement,
                  Fragment: window.React.Fragment,
                };
                export const { jsx, jsxs, jsxDEV, Fragment } = jsxRuntime;
              `,
              loader: "js",
            };
          }
          if (args.path === "react-dom") {
            return {
              contents: `
                const ReactDOM = window.ReactDOM;
                export default ReactDOM;
                export const { createRoot, hydrateRoot, createPortal, flushSync } = ReactDOM;
              `,
              loader: "js",
            };
          }
          return null;
        });
      },
    };

    const result = await Bun.build({
      entrypoints: [entrypoint],
      target: "browser",
      format: "iife",
      minify: process.env.NODE_ENV === "production",
      sourcemap: process.env.NODE_ENV !== "production" ? "inline" : "none",
      define: {
        "process.env.NODE_ENV": JSON.stringify(process.env.NODE_ENV || "development"),
      },
      naming: "[name].[ext]",
      plugins: [reactGlobalPlugin],
    });

    // Restore original directory
    process.chdir(originalDir);

    if (!result.success) {
      console.error("Build logs:");
      for (const log of result.logs) {
        console.error("  -", log);
      }
      const errors = result.logs.map(log => log.message || String(log)).join("\n");
      return {
        pluginId,
        success: false,
        error: errors || "Unknown build error",
      };
    }

    let js = "";
    let css = "";

    for (const output of result.outputs) {
      const text = await output.text();
      if (output.kind === "entry-point") {
        js = text;
      } else if (output.kind === "asset" && output.path.endsWith(".css")) {
        css = text;
      }
    }

    // Create output directory
    const pluginOutputDir = join(outputDir, pluginId);
    if (!existsSync(pluginOutputDir)) {
      mkdirSync(pluginOutputDir, { recursive: true });
    }

    // Write outputs
    const jsPath = join(pluginOutputDir, "bundle.js");
    const cssPath = join(pluginOutputDir, "bundle.css");
    const manifestPath = join(pluginOutputDir, "manifest.json");

    await Bun.write(jsPath, js);
    if (css) {
      await Bun.write(cssPath, css);
    }

    // Generate manifest
    const manifest = {
      pluginId,
      version: pluginVersion,
      builtAt: new Date().toISOString(),
      files: {
        js: "bundle.js",
        css: css ? "bundle.css" : null,
      },
    };
    await Bun.write(manifestPath, JSON.stringify(manifest, null, 2));

    console.log(`        Output: ${jsPath}`);
    if (css) {
      console.log(`        CSS: ${cssPath}`);
    }

    return {
      pluginId,
      success: true,
      outputPath: jsPath,
      js,
      css,
    };
  } catch (error) {
    return {
      pluginId,
      success: false,
      error: String(error),
    };
  }
}

/**
 * Build all plugins or specific ones
 */
async function buildPlugins(pluginIds?: string[]): Promise<PluginBuildResult[]> {
  const plugins = pluginIds && pluginIds.length > 0
    ? pluginIds
    : findPluginsWithUI();

  if (plugins.length === 0) {
    console.log("No plugins with UI found");
    return [];
  }

  console.log(`\nBuilding ${plugins.length} plugin(s)...\n`);

  const results: PluginBuildResult[] = [];
  for (const pluginId of plugins) {
    const result = await buildPlugin(pluginId);
    results.push(result);

    if (result.success) {
      console.log(`        ✓ ${pluginId} built successfully\n`);
    } else {
      console.error(`        ✗ ${pluginId} failed: ${result.error}\n`);
    }
  }

  return results;
}

// Parse arguments
const args = process.argv.slice(2);
const watchMode = args.includes("--watch") || args.includes("-w");
const pluginArgs = args.filter(arg => !arg.startsWith("-"));

// Initial build
const results = await buildPlugins(pluginArgs.length > 0 ? pluginArgs : undefined);

const successful = results.filter(r => r.success).length;
const failed = results.filter(r => !r.success).length;

console.log(`\nBuild complete: ${successful} succeeded, ${failed} failed`);

if (watchMode) {
  console.log("\nWatching for changes...");

  // Watch plugin source directories
  const chokidar = await import("chokidar");
  const plugins = pluginArgs.length > 0 ? pluginArgs : findPluginsWithUI();
  const watchDirs = plugins.map(p => join(pluginsDir, p, "ui", "src"));

  let rebuildTimeout: ReturnType<typeof setTimeout> | null = null;
  let pendingPlugins = new Set<string>();

  const watcher = chokidar.default.watch(watchDirs, {
    ignoreInitial: true,
    ignored: /(^|[\/\\])\../,
  });

  watcher.on("all", (event, filePath) => {
    if (!filePath.endsWith(".ts") && !filePath.endsWith(".tsx") && !filePath.endsWith(".css")) {
      return;
    }

    // Figure out which plugin this file belongs to
    for (const pluginId of plugins) {
      if (filePath.includes(join(pluginsDir, pluginId))) {
        pendingPlugins.add(pluginId);
        break;
      }
    }

    // Debounce rebuilds
    if (rebuildTimeout) clearTimeout(rebuildTimeout);
    rebuildTimeout = setTimeout(async () => {
      const toRebuild = [...pendingPlugins];
      pendingPlugins.clear();

      console.log(`\nRebuilding: ${toRebuild.join(", ")}...`);
      await buildPlugins(toRebuild);
    }, 100);
  });
}

export { buildPlugin, buildPlugins, findPluginsWithUI };
