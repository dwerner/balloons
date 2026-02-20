// Simple dev server for Bun with bundling
import chokidar from "chokidar";
import { join, dirname } from "path";

const projectDir = import.meta.dir;
const webDir = dirname(projectDir); // web/

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

// Debug log file for browser logs
const debugLogPath = join(projectDir, "browser-debug.log");

const server = Bun.serve({
  port: 3000,
  hostname: "0.0.0.0", // Bind to all interfaces for LAN access
  async fetch(req) {
    const url = new URL(req.url);
    let path = url.pathname;

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

console.log(`
╔══════════════════════════════════════════════════════════════╗
║  Balloons Web UI Dev Server                                 ║
╠══════════════════════════════════════════════════════════════╣
║  Local:   http://localhost:${server.port}                            ║
║  LAN:     http://${localIP}:${server.port}
║                                                             ║
║  WebSocket server should be accessible from browser at:    ║
║  ws://<server-ip>:8765                                      ║
║                                                             ║
║  The UI auto-detects the WS host from the page URL.        ║
║  Override with: ?ws=host:port                               ║
╚══════════════════════════════════════════════════════════════╝
`);
