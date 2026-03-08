// Simple dev server for Bun with bundling - TLS version
// Uses the same certs as the balloons backend from ~/.balloons/certs/
//
// Usage: bun run dev-server-tls.ts [--port <port>] [--no-watch]
//
import chokidar from "chokidar";
import { join, dirname } from "path";
import { homedir } from "os";
import { parseArgs } from "util";

// Parse command line arguments
const { values: args } = parseArgs({
  args: Bun.argv.slice(2),
  options: {
    port: { type: "string", short: "p", default: "3030" },
    "no-watch": { type: "boolean", default: false },
  },
  strict: false,
});

const port = parseInt(args.port || "3030", 10);
const noWatch = args["no-watch"] || false;

const projectDir = import.meta.dir;
const webDir = dirname(projectDir); // web/

// TLS cert paths (same as backend)
const certsDir = join(homedir(), ".balloons", "certs");
const certPath = join(certsDir, "dev.crt");
const keyPath = join(certsDir, "dev.key");

// Check if certs exist
const certFile = Bun.file(certPath);
const keyFile = Bun.file(keyPath);

if (!(await certFile.exists()) || !(await keyFile.exists())) {
  console.error(`
TLS certificates not found!

Expected:
  ${certPath}
  ${keyPath}

Generate them with:
  python scripts/generate_dev_certs.py
`);
  process.exit(1);
}

// Build outputs
interface BuildOutput {
  js: string;
  css: string;
}

// Build the app bundle
async function buildApp(): Promise<BuildOutput | null> {
  const entrypoint = join(projectDir, "src/main.tsx");

  const result = await Bun.build({
    entrypoints: [entrypoint],
    target: "browser",
    minify: false,
    sourcemap: "inline",
    define: {
      "process.env.NODE_ENV": '"development"',
    },
  });

  if (!result.success) {
    console.error("Build failed:");
    for (const log of result.logs) {
      console.error(log);
    }
    return null;
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

  return { js, css };
}

// Initial build
let buildOutput = await buildApp();

// Watch for changes and rebuild using chokidar (reliable on Linux)
const dirsToWatch = [
  join(projectDir, "src"),
  join(webDir, "generated"),
];

// Debounce rebuilds to avoid multiple rapid rebuilds
let rebuildTimeout: ReturnType<typeof setTimeout> | null = null;

const watcher = chokidar.watch(dirsToWatch, {
  ignoreInitial: true,
  ignored: /(^|[\/\\])\../, // ignore dotfiles
});

// Only watch if not disabled
if (!noWatch) {
  watcher.on("all", async (event, filePath) => {
    if (filePath.endsWith(".ts") || filePath.endsWith(".tsx") || filePath.endsWith(".css")) {
      // Debounce: wait 50ms for more changes before rebuilding
      if (rebuildTimeout) clearTimeout(rebuildTimeout);
      rebuildTimeout = setTimeout(async () => {
        console.log(`${event}: ${filePath}, rebuilding...`);
        const newBuild = await buildApp();
        if (newBuild) {
          buildOutput = newBuild;
          console.log("Rebuild complete");
        }
      }, 50);
    }
  });

  watcher.on("ready", () => {
    console.log(`Watching ${dirsToWatch.join(", ")}`);
  });
} else {
  // Close watcher if not needed
  watcher.close();
  console.log("File watching disabled (--no-watch)");
}

// Debug log file for browser logs
const debugLogPath = join(projectDir, "browser-debug.log");

// STT WebSocket proxy configuration
// This proxies wss:// connections to the RealtimeSTT server (ws://)
const STT_PROXY_HOST = process.env.STT_HOST || "192.168.0.120";
const STT_PROXY_PORT = parseInt(process.env.STT_PORT || "8012", 10);

const server = Bun.serve({
  port: port,
  hostname: "0.0.0.0", // Bind to all interfaces for LAN access
  tls: {
    cert: certFile,
    key: keyFile,
  },
  // WebSocket handler for STT proxy
  websocket: {
    open(ws) {
      // Connection to client opened, connect to upstream STT server
      const upstream = new WebSocket(`ws://${STT_PROXY_HOST}:${STT_PROXY_PORT}`);

      upstream.onopen = () => {
        console.log(`[STT Proxy] Connected to upstream ${STT_PROXY_HOST}:${STT_PROXY_PORT}`);
        // Store upstream reference on ws for later use
        (ws as any).upstream = upstream;
      };

      upstream.onmessage = (event) => {
        // Forward messages from STT server to browser
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(event.data);
        }
      };

      upstream.onerror = (error) => {
        console.error("[STT Proxy] Upstream error:", error);
        ws.close();
      };

      upstream.onclose = () => {
        console.log("[STT Proxy] Upstream closed");
        ws.close();
      };
    },
    message(ws, message) {
      // Forward messages from browser to STT server
      const upstream = (ws as any).upstream as WebSocket | undefined;
      if (upstream && upstream.readyState === WebSocket.OPEN) {
        upstream.send(message);
      }
    },
    close(ws) {
      // Clean up upstream connection
      const upstream = (ws as any).upstream as WebSocket | undefined;
      if (upstream) {
        upstream.close();
      }
      console.log("[STT Proxy] Client disconnected");
    },
  },
  async fetch(req, server) {
    const url = new URL(req.url);
    let path = url.pathname;

    // WebSocket upgrade for STT proxy
    if (path === "/stt-proxy") {
      const upgraded = server.upgrade(req);
      if (upgraded) {
        return undefined; // Bun handles the upgrade
      }
      return new Response("WebSocket upgrade failed", { status: 400 });
    }

    // Debug log endpoint - receives logs from browser
    if (path === "/debug-log" && req.method === "POST") {
      try {
        const body = await req.json();
        const timestamp = new Date().toISOString();
        const logLine = `[${timestamp}] ${JSON.stringify(body)}\n`;
        await Bun.write(debugLogPath, await Bun.file(debugLogPath).text().catch(() => "") + logLine);
        console.log("[Browser Log]", body.message || body);
        return new Response("OK", { status: 200 });
      } catch (e) {
        return new Response("Error", { status: 500 });
      }
    }

    // Clear debug log
    if (path === "/debug-log" && req.method === "DELETE") {
      await Bun.write(debugLogPath, "");
      return new Response("Cleared", { status: 200 });
    }

    // Read debug log
    if (path === "/debug-log" && req.method === "GET") {
      const content = await Bun.file(debugLogPath).text().catch(() => "No logs yet");
      return new Response(content, { headers: { "Content-Type": "text/plain" } });
    }

    // Proxy survey API requests to the survey server (port 3001)
    // This avoids mixed content issues (HTTPS page -> HTTP API)
    if (path.startsWith("/api/survey")) {
      try {
        const surveyUrl = `http://localhost:3001${path}`;
        const proxyRes = await fetch(surveyUrl, {
          method: req.method,
          headers: req.headers,
          body: req.method !== "GET" && req.method !== "HEAD" ? await req.text() : undefined,
        });
        return new Response(proxyRes.body, {
          status: proxyRes.status,
          headers: proxyRes.headers,
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: "Survey server not reachable" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    // Serve index.html for root
    if (path === "/") {
      path = "/index.html";
    }

    // Serve the bundled JavaScript
    if (path === "/src/main.tsx" || path === "/bundle.js") {
      if (buildOutput?.js) {
        return new Response(buildOutput.js, {
          headers: {
            "Content-Type": "application/javascript",
            "Cache-Control": "no-cache",
          },
        });
      }
      return new Response("Build failed", { status: 500 });
    }

    // Serve the bundled CSS
    if (path === "/bundle.css") {
      if (buildOutput?.css) {
        return new Response(buildOutput.css, {
          headers: {
            "Content-Type": "text/css",
            "Cache-Control": "no-cache",
          },
        });
      }
      return new Response("/* No CSS */", {
        headers: { "Content-Type": "text/css" },
      });
    }

    // Serve plugin bundles - /api/plugins/{pluginId}/bundle.js
    const pluginMatch = path.match(/^\/api\/plugins\/([^/]+)\/(.+)$/);
    if (pluginMatch) {
      const pluginId = pluginMatch[1];
      const filename = pluginMatch[2];
      if (!pluginId || !filename) {
        return new Response("Invalid plugin path", { status: 400 });
      }
      const pluginsDir = join(dirname(projectDir), "..", "plugins", "dist", pluginId);
      const pluginFile = Bun.file(join(pluginsDir, filename));

      if (await pluginFile.exists()) {
        const contentType = filename.endsWith(".js")
          ? "application/javascript"
          : filename.endsWith(".css")
          ? "text/css"
          : filename.endsWith(".json")
          ? "application/json"
          : "application/octet-stream";

        return new Response(pluginFile, {
          headers: {
            "Content-Type": contentType,
            "Cache-Control": "no-cache",
          },
        });
      }
      return new Response(`Plugin file not found: ${pluginId}/${filename}`, { status: 404 });
    }

    // List available plugins - /api/plugins
    if (path === "/api/plugins") {
      const pluginsDistDir = join(dirname(projectDir), "..", "plugins", "dist");
      const plugins: { id: string; manifest: any }[] = [];

      try {
        const entries = await Array.fromAsync(new Bun.Glob("*/manifest.json").scan({ cwd: pluginsDistDir }));
        for (const entry of entries) {
          const pluginId = entry.replace("/manifest.json", "");
          const manifestFile = Bun.file(join(pluginsDistDir, entry));
          if (await manifestFile.exists()) {
            const manifest = await manifestFile.json();
            plugins.push({ id: pluginId, manifest });
          }
        }
      } catch (e) {
        // dist dir may not exist
      }

      return new Response(JSON.stringify(plugins), {
        headers: { "Content-Type": "application/json" },
      });
    }

    // Try to serve static files
    const filePath = join(projectDir, path);
    const file = Bun.file(filePath);

    if (await file.exists()) {
      return new Response(file);
    }

    return new Response("Not found", { status: 404 });
  },
});

// Get local IP for display
import { networkInterfaces } from "os";
function getLocalIP(): string {
  const nets = networkInterfaces();
  for (const name of Object.keys(nets)) {
    for (const net of nets[name] ?? []) {
      if (net.family === "IPv4" && !net.internal) {
        return net.address;
      }
    }
  }
  return "localhost";
}

const localIP = getLocalIP();

const watchStatus = noWatch ? "disabled" : "enabled";
console.log(`
╔══════════════════════════════════════════════════════════════╗
║  Balloons Web UI Dev Server (TLS)                           ║
╠══════════════════════════════════════════════════════════════╣
║  Local:   https://localhost:${server.port.toString().padEnd(5)}                        ║
║  LAN:     https://${localIP}:${server.port.toString().padEnd(5)}                   ║
║                                                              ║
║  Using self-signed cert from ~/.balloons/certs/              ║
║  File watching: ${watchStatus.padEnd(43)}║
╚══════════════════════════════════════════════════════════════╝
`);
