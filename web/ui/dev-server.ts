// Simple dev server for Bun with bundling
import { watch } from "fs";
import { join, dirname } from "path";

const projectDir = import.meta.dir;
const webDir = dirname(projectDir); // web/

// Build the app bundle
async function buildApp(): Promise<string | null> {
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

  const output = result.outputs[0];
  return output ? await output.text() : null;
}

// Initial build
let bundleCode = await buildApp();

// Watch for changes and rebuild
const dirsToWatch = [
  join(projectDir, "src"),
  join(webDir, "generated"),
];

for (const dir of dirsToWatch) {
  try {
    watch(dir, { recursive: true }, async (event, filename) => {
      if (filename?.endsWith(".ts") || filename?.endsWith(".tsx")) {
        console.log(`File changed: ${filename}, rebuilding...`);
        const newBundle = await buildApp();
        if (newBundle) {
          bundleCode = newBundle;
          console.log("Rebuild complete");
        }
      }
    });
    console.log(`Watching ${dir}`);
  } catch (e) {
    console.warn(`Could not watch ${dir}:`, e);
  }
}

const server = Bun.serve({
  port: 3000,
  hostname: "0.0.0.0", // Bind to all interfaces for LAN access
  async fetch(req) {
    const url = new URL(req.url);
    let path = url.pathname;

    // Serve index.html for root
    if (path === "/") {
      path = "/index.html";
    }

    // Serve the bundled JavaScript
    if (path === "/src/main.tsx" || path === "/bundle.js") {
      if (bundleCode) {
        return new Response(bundleCode, {
          headers: {
            "Content-Type": "application/javascript",
            "Cache-Control": "no-cache",
          },
        });
      }
      return new Response("Build failed", { status: 500 });
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
