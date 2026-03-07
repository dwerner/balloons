/**
 * Survey Server - Bun HTTP server for parenting feedback surveys
 *
 * Endpoints:
 * - GET /survey/:id - Serve survey form
 * - GET /api/survey/:id - Get survey data (JSON)
 * - POST /api/survey/:id/respond - Submit response
 * - POST /api/survey - Create new survey (for CLI/API use)
 * - GET /api/surveys/responses - List all responses
 *
 * Data storage:
 * - data/pending/{id}.json - Active surveys
 * - data/responses/{id}.json - Completed responses
 */

import { join } from "path";
import { networkInterfaces } from "os";
import type { PendingSurvey, SurveyResponse, QuestionAnswer } from "./types";

const projectDir = import.meta.dir;
const dataDir = join(projectDir, "data");
const pendingDir = join(dataDir, "pending");
const responsesDir = join(dataDir, "responses");

// Build client JS
async function buildClient(): Promise<string | null> {
  const entrypoint = join(projectDir, "survey-client.ts");

  const result = await Bun.build({
    entrypoints: [entrypoint],
    target: "browser",
    minify: false,
    sourcemap: "inline",
  });

  if (!result.success) {
    console.error("Client build failed:", result.logs);
    return null;
  }

  for (const output of result.outputs) {
    if (output.kind === "entry-point") {
      return await output.text();
    }
  }
  return null;
}

let clientJs = await buildClient();

// Watch for changes and rebuild
const watcher = Bun.spawn(["sh", "-c", `
  while true; do
    inotifywait -e modify "${join(projectDir, 'survey-client.ts')}" 2>/dev/null
    echo "Rebuilding client..."
  done
`], {
  stdout: "pipe",
});

// Helper functions
function generateId(): string {
  return Math.random().toString(36).substring(2, 10);
}

async function getPendingSurvey(id: string): Promise<PendingSurvey | null> {
  const file = Bun.file(join(pendingDir, `${id}.json`));
  if (await file.exists()) {
    return await file.json();
  }
  return null;
}

async function savePendingSurvey(survey: PendingSurvey): Promise<void> {
  await Bun.write(
    join(pendingDir, `${survey.id}.json`),
    JSON.stringify(survey, null, 2)
  );
}

async function saveResponse(response: SurveyResponse): Promise<void> {
  await Bun.write(
    join(responsesDir, `${response.surveyId}.json`),
    JSON.stringify(response, null, 2)
  );
}

async function deletePendingSurvey(id: string): Promise<void> {
  const file = Bun.file(join(pendingDir, `${id}.json`));
  if (await file.exists()) {
    await Bun.$`rm ${join(pendingDir, `${id}.json`)}`;
  }
}

async function getAllResponses(): Promise<SurveyResponse[]> {
  const responses: SurveyResponse[] = [];
  const glob = new Bun.Glob("*.json");

  for await (const file of glob.scan(responsesDir)) {
    const content = await Bun.file(join(responsesDir, file)).json();
    responses.push(content);
  }

  return responses.sort((a, b) =>
    new Date(b.submittedAt).getTime() - new Date(a.submittedAt).getTime()
  );
}

async function getAllPendingSurveys(): Promise<PendingSurvey[]> {
  const surveys: PendingSurvey[] = [];
  const glob = new Bun.Glob("*.json");

  for await (const file of glob.scan(pendingDir)) {
    const content = await Bun.file(join(pendingDir, file)).json();
    surveys.push(content);
  }

  return surveys.sort((a, b) =>
    new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
}

// Server
const server = Bun.serve({
  port: 3001,
  hostname: "0.0.0.0",

  async fetch(req) {
    const url = new URL(req.url);
    const path = url.pathname;

    // CORS headers for API
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (req.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    // API: Create new survey
    if (path === "/api/survey" && req.method === "POST") {
      try {
        const body = await req.json();
        const survey: PendingSurvey = {
          id: generateId(),
          childName: body.childName,
          incidentTitle: body.incidentTitle,
          incidentDescription: body.incidentDescription,
          feedbackPrompt: body.feedbackPrompt || "I'd love to hear your honest thoughts.",
          createdAt: new Date().toISOString(),
          createdBy: body.createdBy || "Dad",
          // Optional: custom questions (array of {id, type, label, required?, placeholder?, ratingLabels?})
          questions: body.questions,
        };

        await savePendingSurvey(survey);

        return Response.json(
          { id: survey.id, url: `http://${getLocalIP()}:3001/survey/${survey.id}` },
          { headers: corsHeaders }
        );
      } catch (e) {
        return Response.json({ error: "Invalid request" }, { status: 400, headers: corsHeaders });
      }
    }

    // API: Get survey data
    const surveyMatch = path.match(/^\/api\/survey\/([a-z0-9]+)$/);
    if (surveyMatch && req.method === "GET") {
      const survey = await getPendingSurvey(surveyMatch[1]);
      if (!survey) {
        return Response.json({ error: "Not found" }, { status: 404, headers: corsHeaders });
      }
      return Response.json(survey, { headers: corsHeaders });
    }

    // API: Submit response
    const respondMatch = path.match(/^\/api\/survey\/([a-z0-9]+)\/respond$/);
    if (respondMatch && req.method === "POST") {
      const surveyId = respondMatch[1];
      const survey = await getPendingSurvey(surveyId);

      if (!survey) {
        return Response.json({ error: "Survey not found or already completed" }, { status: 404, headers: corsHeaders });
      }

      try {
        const body = await req.json();

        // Support both legacy (rating + writtenResponse) and new (answers array) formats
        const response: SurveyResponse = {
          surveyId,
          childName: survey.childName,
          incidentTitle: survey.incidentTitle,
          submittedAt: new Date().toISOString(),
        };

        if (body.answers) {
          // New format: array of question answers
          response.answers = body.answers as QuestionAnswer[];
        } else {
          // Legacy format: single rating + text
          response.rating = body.rating;
          response.writtenResponse = body.writtenResponse || "";
        }

        await saveResponse(response);
        await deletePendingSurvey(surveyId);

        return Response.json({ success: true }, { headers: corsHeaders });
      } catch (e) {
        return Response.json({ error: "Invalid request" }, { status: 400, headers: corsHeaders });
      }
    }

    // API: List all responses
    if (path === "/api/surveys/responses" && req.method === "GET") {
      const responses = await getAllResponses();
      return Response.json(responses, { headers: corsHeaders });
    }

    // API: List pending surveys
    if (path === "/api/surveys/pending" && req.method === "GET") {
      const pending = await getAllPendingSurveys();
      return Response.json(pending, { headers: corsHeaders });
    }

    // Serve survey page
    const pageMatch = path.match(/^\/survey\/([a-z0-9]+)$/);
    if (pageMatch) {
      const htmlFile = Bun.file(join(projectDir, "survey.html"));
      return new Response(htmlFile, {
        headers: { "Content-Type": "text/html" },
      });
    }

    // Serve static files
    if (path === "/survey.css") {
      const file = Bun.file(join(projectDir, "survey.css"));
      return new Response(file, {
        headers: { "Content-Type": "text/css" },
      });
    }

    if (path === "/survey-client.js") {
      // Rebuild if needed
      if (!clientJs) {
        clientJs = await buildClient();
      }
      return new Response(clientJs || "// Build failed", {
        headers: { "Content-Type": "application/javascript" },
      });
    }

    // Root redirect
    if (path === "/") {
      return new Response("Survey server running. Surveys are created via API.", {
        headers: { "Content-Type": "text/plain" },
      });
    }

    return new Response("Not found", { status: 404 });
  },
});

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
║  Parenting Feedback Survey Server                            ║
╠══════════════════════════════════════════════════════════════╣
║  Local:   http://localhost:${server.port}                            ║
║  LAN:     http://${localIP}:${server.port}
║                                                              ║
║  Create surveys via API:                                     ║
║  POST http://localhost:${server.port}/api/survey                     ║
║                                                              ║
║  Data stored in: ${dataDir}
╚══════════════════════════════════════════════════════════════╝
`);
