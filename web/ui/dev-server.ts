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

// Typecheck in the background after each build.
// Bun.build strips types without checking them, so without this a broken
// type (or a call to a method that no longer exists on the generated client)
// ships silently and only fails at runtime. Runs async so it never stalls
// the rebuild/serve loop.
let typecheckProc: ReturnType<typeof Bun.spawn> | null = null;
function runTypecheck(): void {
  if (typecheckProc) {
    try {
      typecheckProc.kill();
    } catch {
      /* already exited */
    }
  }
  const proc = Bun.spawn(["bun", "x", "tsc", "--noEmit"], {
    cwd: projectDir,
    stdout: "pipe",
    stderr: "pipe",
  });
  typecheckProc = proc;

  // Start draining the pipes immediately; reading after `exited` resolves
  // can lose buffered output.
  const outP = new Response(proc.stdout).text();
  const errP = new Response(proc.stderr).text();

  proc.exited.then(async (code) => {
    if (typecheckProc === proc) typecheckProc = null;
    const [o, e] = await Promise.all([outP, errP]);
    const text = (o + e).trim();
    if (code === 0) {
      console.log("\x1b[32m[typecheck] OK\x1b[0m");
    } else {
      console.error("\x1b[31m[typecheck] FAILED\x1b[0m");
      console.error(text);
    }
  });
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
runTypecheck();

// Watch for changes and rebuild using chokidar (reliable on Linux)
const dirsToWatch = [
  join(projectDir, "src"),
  join(webDir, "generated"),
];

// Debounce rebuilds to avoid multiple rapid rebuilds
let rebuildTimeout: ReturnType<typeof setTimeout> | null = null;

const watcher = chokidar.watch(dirsToWatch, {
  ignoreInitial: true,
  ignored: /(^|[/\\])\../, // ignore dotfiles
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
      runTypecheck();
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
