# Post-Hoc LLM Analysis Service: Deep Dive

This document details the mechanics of the post-hoc LLM analysis service—how it gathers context, builds prompts, interfaces with local models, parses responses, and stores structured evaluation data.

## Overview

The analysis service performs **batch evaluation** of completed sessions using an LLM. Unlike interactive chat, this is a single-shot completion:

1. Gather all relevant data (session, markers, flags, etc.)
2. Build a structured prompt with the full context
3. Send to a local model (no tool calling needed)
4. Parse the JSON response into typed data
5. Store the analysis for later querying

**Why local models work well for this:**
- No tool calling required (just structured JSON output)
- Not user-facing latency (can take 30-60s without issue)
- Context is bounded (session + markers, not open-ended exploration)
- Runs infrequently (per-session, not per-turn)
- Saves API costs on high-volume analysis

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      EvaluationService                          │
│  (WebSocket-exposed, service/evaluation_service.py)             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  analyze_session(session_id, backend_name?)                     │
│      │                                                          │
│      ├─► 1. ContextGatherer.gather(session_id)                  │
│      │       → loads session, markers, flags, stop events       │
│      │                                                          │
│      ├─► 2. PromptBuilder.build(context)                        │
│      │       → renders Jinja2 template with all data            │
│      │                                                          │
│      ├─► 3. LocalModelClient.complete(prompt, backend)          │
│      │       → sends to ollama/llamacpp, gets JSON response     │
│      │                                                          │
│      ├─► 4. ResponseParser.parse(response)                      │
│      │       → validates JSON, extracts scores/analysis         │
│      │                                                          │
│      └─► 5. Store.save_analysis(PostHocAnalysis)                │
│              → persists to LMDB                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Step 1: Context Gathering

The `ContextGatherer` loads all evaluation-relevant data for a session:

```python
@dataclass
class AnalysisContext:
    """All data needed for post-hoc analysis."""

    # Session basics
    session_id: str
    session_title: str
    backend_name: str
    model_name: str

    # Timing
    started_at: str  # First turn timestamp
    ended_at: str    # Last turn timestamp
    duration_minutes: int

    # Counts
    turn_count: int
    exchange_count: int  # Distinct exchange_ids
    tool_call_count: int

    # The conversation
    turns: list[Turn]  # Full turn history

    # Automatic markers
    behavior_markers: list[BehaviorMarker]
    user_sentiment_markers: list[UserSentimentMarker]
    stop_events: list[StopEvent]

    # Manual annotations
    turn_flags: list[TurnFlag]
    sentiment_summary: dict[str, int]  # {"excellent": 2, "poor": 1}

    # Existing review if any
    existing_review: ReviewData | None


class ContextGatherer:
    """Gathers all context needed for session analysis."""

    def __init__(self, store: Storage, session_manager: SessionManager):
        self._store = store
        self._session_manager = session_manager

    async def gather(self, session_id: str) -> AnalysisContext:
        """Load all analysis context for a session."""

        # Load session with full turn history
        session = await self._session_manager.load_session(session_id)

        # Compute timing
        turns = session.turns
        started_at = turns[0].timestamp if turns else ""
        ended_at = turns[-1].timestamp if turns else ""
        duration = self._compute_duration(started_at, ended_at)

        # Count exchanges (distinct exchange_ids)
        exchange_ids = {t.exchange_id for t in turns if t.exchange_id}

        # Count tool calls
        tool_calls = sum(
            1 for t in turns
            if isinstance(t.content_block, ToolUseBlock)
        )

        # Load automatic markers
        behavior_markers = await self._store.get_behavior_markers(session_id)
        user_sentiment = await self._store.get_user_sentiment_markers(session_id)
        stop_events = await self._store.get_stop_events(session_id)

        # Load manual annotations
        turn_flags = await self._store.get_turn_flags(session_id)

        # Compute sentiment summary
        sentiment_summary = self._compute_sentiment_summary(turns)

        # Load existing review if any
        reviews = await self._store.get_reviews(session_id)
        existing_review = reviews[0] if reviews else None

        return AnalysisContext(
            session_id=session_id,
            session_title=session.title,
            backend_name=session.backend_name,
            model_name=session.model,
            started_at=started_at,
            ended_at=ended_at,
            duration_minutes=duration,
            turn_count=len(turns),
            exchange_count=len(exchange_ids),
            tool_call_count=tool_calls,
            turns=turns,
            behavior_markers=behavior_markers,
            user_sentiment_markers=user_sentiment,
            stop_events=stop_events,
            turn_flags=turn_flags,
            sentiment_summary=sentiment_summary,
            existing_review=existing_review,
        )

    def _compute_sentiment_summary(self, turns: list[Turn]) -> dict[str, int]:
        """Count sentiment ratings across turns."""
        counts: dict[str, int] = {}
        for turn in turns:
            if turn.sentiment:
                counts[turn.sentiment.value] = counts.get(turn.sentiment.value, 0) + 1
        return counts
```

## Step 2: Prompt Building

The `PromptBuilder` renders a Jinja2 template with the gathered context. The prompt is structured to encourage reliable JSON output:

```python
class PromptBuilder:
    """Builds analysis prompts from context."""

    def __init__(self, template_path: Path | None = None):
        self._template_path = template_path or Path(__file__).parent / "prompts" / "analysis.md.j2"
        self._env = Environment(
            loader=FileSystemLoader(self._template_path.parent),
            autoescape=False,  # Markdown, not HTML
        )

    def build(self, ctx: AnalysisContext) -> str:
        """Build the analysis prompt."""
        template = self._env.get_template(self._template_path.name)

        return template.render(
            session=ctx,
            conversation=self._format_conversation(ctx.turns),
            behavior_markers=self._format_markers(ctx.behavior_markers),
            user_sentiment=self._format_sentiment_markers(ctx.user_sentiment_markers),
            stop_events=self._format_stop_events(ctx.stop_events),
            turn_flags=self._format_flags(ctx.turn_flags),
            sentiment_summary=ctx.sentiment_summary,
            existing_review=ctx.existing_review,
        )

    def _format_conversation(self, turns: list[Turn]) -> str:
        """Format conversation for the prompt.

        Truncates very long tool results to keep context manageable.
        """
        lines = []
        for i, turn in enumerate(turns):
            # Add turn header
            role_marker = "👤" if turn.role == "user" else "🤖" if turn.role == "assistant" else "🔧"
            sentiment_marker = f" [{turn.sentiment.value}]" if turn.sentiment else ""
            lines.append(f"\n### Turn {i+1} ({role_marker} {turn.role}){sentiment_marker}")

            # Format content based on block type
            block = turn.content_block
            if isinstance(block, TextBlock):
                lines.append(block.text)
            elif isinstance(block, ToolUseBlock):
                lines.append(f"**Tool: {block.name}**")
                lines.append(f"```json\n{json.dumps(block.input, indent=2)[:500]}\n```")
            elif isinstance(block, ToolResultBlock):
                content = block.content
                if len(content) > 1000:
                    content = content[:500] + "\n...[truncated]...\n" + content[-200:]
                lines.append(f"```\n{content}\n```")
            elif isinstance(block, InterruptionBlock):
                lines.append(f"**[Interrupted: {block.reason}]**")
            elif isinstance(block, ErrorBlock):
                lines.append(f"**[Error: {block.reason}]**")

        return "\n".join(lines)

    def _format_markers(self, markers: list[BehaviorMarker]) -> str:
        """Format behavior markers for the prompt."""
        if not markers:
            return "_No behavior markers detected_"

        lines = []
        for m in markers:
            lines.append(f"- **{m.marker_type}** ({m.severity}, confidence={m.confidence:.0%})")
            if m.details:
                for k, v in m.details.items():
                    lines.append(f"  - {k}: {v}")
        return "\n".join(lines)
```

### The Analysis Template

```markdown
{# prompts/analysis.md.j2 #}
# Session Post-Hoc Analysis

You are analyzing a coding assistant session to evaluate model performance.
Provide a structured evaluation based on the conversation and detected markers.

## Session Context

- **Model**: {{ session.model_name }}
- **Backend**: {{ session.backend_name }}
- **Duration**: {{ session.duration_minutes }} minutes
- **Turns**: {{ session.turn_count }}
- **Exchanges**: {{ session.exchange_count }}
- **Tool Calls**: {{ session.tool_call_count }}

## Detected Behavior Markers

{{ behavior_markers }}

## User Sentiment Markers

{{ user_sentiment }}

## Stop Events

{% if stop_events %}
{% for event in stop_events %}
- **{{ event.stop_type }}** after {{ event.duration_ms }}ms ({{ event.tokens_streamed }} tokens)
  {% if event.error_message %}Error: {{ event.error_message }}{% endif %}
{% endfor %}
{% else %}
_No abnormal stop events_
{% endif %}

## Manual Turn Flags

{% if turn_flags %}
{% for flag in turn_flags %}
- **{{ flag.flag_type }}** on turn {{ flag.turn_id }}{% if flag.note %}: {{ flag.note }}{% endif %}
{% endfor %}
{% else %}
_No manual flags_
{% endif %}

## Turn Sentiment Ratings

{% if sentiment_summary %}
{% for sentiment, count in sentiment_summary.items() %}
- {{ sentiment }}: {{ count }} turn(s)
{% endfor %}
{% else %}
_No sentiment ratings_
{% endif %}

{% if existing_review %}
## User's Previous Review

The user already reviewed this session:
- Correctness: {{ existing_review.score_correctness }}/5
- Efficiency: {{ existing_review.score_efficiency }}/5
- Task: {{ existing_review.task_category }} - {{ existing_review.task_description }}
- User notes: {{ existing_review.user_summary }}
{% endif %}

## Conversation History

{{ conversation }}

---

## Your Tasks

Analyze the session and provide structured evaluation. Consider:
1. How do the automatic markers correlate with actual quality issues?
2. Do user sentiment markers align with the conversation flow?
3. What patterns emerge from the tool usage and error handling?

### Required Output Format

Respond with ONLY a JSON object (no markdown code fences, no explanation):

{
  "scores": {
    "correctness": {"score": <1-5>, "reasoning": "<brief justification>"},
    "efficiency": {"score": <1-5>, "reasoning": "<brief justification>"},
    "instruction_following": {"score": <1-5>, "reasoning": "<brief justification>"},
    "recovery": {"score": <1-5>, "reasoning": "<brief justification>"},
    "autonomy": {"score": <1-5>, "reasoning": "<brief justification>"},
    "judgment": {"score": <1-5>, "reasoning": "<brief justification>"},
    "communication": {"score": <1-5>, "reasoning": "<brief justification>"}
  },
  "pattern_analysis": "<What patterns do you see across markers and sentiment?>",
  "marker_correlation": "<How do automatic markers relate to actual issues?>",
  "key_moments": ["<critical moment 1>", "<critical moment 2>"],
  "recommendations": "<What could improve similar sessions?>",
  "summary": "<2-3 sentence overall assessment>"
}
```

## Step 3: Local Model Client

The `LocalModelClient` interfaces with local models via the OpenAI-compatible API:

```python
class LocalModelClient:
    """Client for local LLM inference via OpenAI-compatible API.

    Supports ollama, llamacpp, and other servers that expose
    OpenAI-compatible /v1/chat/completions endpoints.
    """

    def __init__(self, config: BackendConfig):
        """Initialize from backend config.

        Args:
            config: Backend configuration (type='openai', base_url set)
        """
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key or "not-needed",
        )
        self._model = config.model or "default"
        self._timeout = 120.0  # 2 minutes for long analyses

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.3,  # Lower for more consistent JSON
        max_tokens: int = 4000,
    ) -> str:
        """Get a completion from the model.

        Args:
            prompt: The user prompt (analysis request)
            system_prompt: Optional system prompt
            temperature: Sampling temperature (lower = more deterministic)
            max_tokens: Maximum response tokens

        Returns:
            The model's response text

        Raises:
            AnalysisError: If the API call fails
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    # No tools - pure text completion
                ),
                timeout=self._timeout,
            )

            if not response.choices:
                raise AnalysisError("Empty response from model")

            return response.choices[0].message.content or ""

        except asyncio.TimeoutError:
            raise AnalysisError(f"Analysis timed out after {self._timeout}s")
        except Exception as e:
            raise AnalysisError(f"Model API error: {e}") from e


class AnalysisError(Exception):
    """Error during analysis."""
    pass
```

## Step 4: Response Parsing

The `ResponseParser` extracts structured data from the JSON response:

```python
@dataclass
class ParsedAnalysis:
    """Parsed analysis result."""
    scores: dict[str, dict[str, Any]]  # {"correctness": {"score": 4, "reasoning": "..."}}
    pattern_analysis: str
    marker_correlation: str
    key_moments: list[str]
    recommendations: str
    summary: str


class ResponseParser:
    """Parses and validates analysis responses."""

    REQUIRED_SCORES = [
        "correctness", "efficiency", "instruction_following",
        "recovery", "autonomy", "judgment", "communication"
    ]

    def parse(self, response: str) -> ParsedAnalysis:
        """Parse JSON response into structured analysis.

        Handles common issues:
        - Markdown code fences around JSON
        - Extra text before/after JSON
        - Missing optional fields

        Args:
            response: Raw model response

        Returns:
            Parsed analysis data

        Raises:
            ParseError: If response cannot be parsed
        """
        # Extract JSON from response (handle markdown fences)
        json_str = self._extract_json(response)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            # Try to salvage partial JSON
            data = self._attempt_recovery(json_str, e)

        # Validate and extract
        return self._build_analysis(data)

    def _extract_json(self, response: str) -> str:
        """Extract JSON from response, handling common formats."""
        text = response.strip()

        # Remove markdown code fences if present
        if text.startswith("```"):
            # Find the end of the fence
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]  # Remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # Remove closing fence
            text = "\n".join(lines)

        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1

        if start == -1 or end == 0:
            raise ParseError(f"No JSON object found in response: {text[:200]}")

        return text[start:end]

    def _attempt_recovery(self, json_str: str, error: json.JSONDecodeError) -> dict:
        """Try to recover from JSON parse errors.

        Common issues:
        - Trailing commas
        - Unescaped newlines in strings
        - Truncated response
        """
        # Try fixing trailing commas
        fixed = re.sub(r',\s*}', '}', json_str)
        fixed = re.sub(r',\s*]', ']', fixed)

        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # Log the failure for debugging
        debug_log.warning(
            f"JSON recovery failed: {error}",
            category=Category.EVALUATION,
            details={
                "json_preview": json_str[:500],
                "error_pos": error.pos,
            }
        )

        raise ParseError(f"Could not parse JSON: {error}")

    def _build_analysis(self, data: dict) -> ParsedAnalysis:
        """Build ParsedAnalysis from validated data."""
        scores = data.get("scores", {})

        # Validate required scores
        for score_name in self.REQUIRED_SCORES:
            if score_name not in scores:
                scores[score_name] = {"score": 0, "reasoning": "Not provided"}
            else:
                score_data = scores[score_name]
                if not isinstance(score_data, dict):
                    scores[score_name] = {"score": int(score_data), "reasoning": ""}
                elif "score" not in score_data:
                    scores[score_name]["score"] = 0
                elif not isinstance(scores[score_name]["score"], int):
                    scores[score_name]["score"] = int(scores[score_name]["score"])

        return ParsedAnalysis(
            scores=scores,
            pattern_analysis=data.get("pattern_analysis", ""),
            marker_correlation=data.get("marker_correlation", ""),
            key_moments=data.get("key_moments", []),
            recommendations=data.get("recommendations", ""),
            summary=data.get("summary", ""),
        )


class ParseError(Exception):
    """Error parsing analysis response."""
    pass
```

## Step 5: Storage

The analysis is stored as a `PostHocAnalysis` record:

```python
# In storage_schema.py (addition to existing file)

@rust_schema
@dataclass
class PostHocAnalysis:
    """LLM-generated post-hoc analysis of a session."""
    id: str  # UUID
    session_id: str
    analysis_backend: str  # Backend that performed analysis
    analysis_model: str  # Model name used

    # Rubric scores with reasoning
    scores: dict  # {"correctness": {"score": 4, "reasoning": "..."}, ...}

    # Analysis sections
    pattern_analysis: str
    marker_correlation: str
    key_moments: list[str]
    recommendations: str
    summary: str

    # Metadata
    generated_at: str  # ISO 8601
    prompt_tokens: int = 0  # Tokens used in prompt
    completion_tokens: int = 0  # Tokens in response
    duration_ms: int = 0  # How long analysis took

    # Optional link to user review
    user_review_id: Optional[str] = None
```

## Complete Service Implementation

```python
# core/evaluation/analysis_service.py

from dataclasses import dataclass
from datetime import datetime
import uuid

from config import BackendConfig, get_config
from .context_gatherer import ContextGatherer, AnalysisContext
from .prompt_builder import PromptBuilder
from .local_model_client import LocalModelClient, AnalysisError
from .response_parser import ResponseParser, ParseError, ParsedAnalysis
from storage_schema import PostHocAnalysis


@dataclass
class AnalysisResult:
    """Result of running analysis."""
    analysis: PostHocAnalysis
    success: bool
    error: str | None = None


class AnalysisService:
    """Service for post-hoc LLM analysis of sessions."""

    def __init__(
        self,
        store,  # Storage
        session_manager,  # SessionManager
        config = None,  # Optional override
    ):
        self._store = store
        self._context_gatherer = ContextGatherer(store, session_manager)
        self._prompt_builder = PromptBuilder()
        self._parser = ResponseParser()
        self._config = config or get_config()

    def _get_analysis_backend(self, backend_name: str | None) -> BackendConfig:
        """Get the backend configuration for analysis.

        Prefers local backends (ollama, llamacpp) to save API costs.
        Falls back to configured default or any available backend.
        """
        if backend_name:
            backend = self._config.get_backend(backend_name)
            if backend:
                return backend

        # Check configured analysis backend
        analysis_backend = self._config.evaluation.analysis.backend
        if analysis_backend:
            backend = self._config.get_backend(analysis_backend)
            if backend:
                return backend

        # Fall back to default backend
        return self._config.get_default_backend()

    async def analyze_session(
        self,
        session_id: str,
        backend_name: str | None = None,
    ) -> AnalysisResult:
        """Run post-hoc analysis on a session.

        Args:
            session_id: Session to analyze
            backend_name: Override the configured analysis backend

        Returns:
            AnalysisResult with the analysis or error
        """
        import time
        start_time = time.perf_counter()

        try:
            # 1. Gather context
            ctx = await self._context_gatherer.gather(session_id)

            # 2. Build prompt
            prompt = self._prompt_builder.build(ctx)

            # 3. Get backend and create client
            backend = self._get_analysis_backend(backend_name)
            client = LocalModelClient(backend)

            # 4. Run completion
            response = await client.complete(
                prompt=prompt,
                system_prompt="You are an expert code review analyst. Respond only with valid JSON.",
                temperature=0.3,
            )

            # 5. Parse response
            parsed = self._parser.parse(response)

            # 6. Build analysis record
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            analysis = PostHocAnalysis(
                id=str(uuid.uuid4()),
                session_id=session_id,
                analysis_backend=backend.name,
                analysis_model=backend.model or "default",
                scores=parsed.scores,
                pattern_analysis=parsed.pattern_analysis,
                marker_correlation=parsed.marker_correlation,
                key_moments=parsed.key_moments,
                recommendations=parsed.recommendations,
                summary=parsed.summary,
                generated_at=datetime.now().isoformat(),
                duration_ms=elapsed_ms,
                user_review_id=ctx.existing_review.id if ctx.existing_review else None,
            )

            # 7. Store
            await self._store.save_post_hoc_analysis(analysis)

            return AnalysisResult(analysis=analysis, success=True)

        except AnalysisError as e:
            return AnalysisResult(
                analysis=None,
                success=False,
                error=f"Analysis failed: {e}",
            )
        except ParseError as e:
            return AnalysisResult(
                analysis=None,
                success=False,
                error=f"Failed to parse response: {e}",
            )
        except Exception as e:
            return AnalysisResult(
                analysis=None,
                success=False,
                error=f"Unexpected error: {e}",
            )
```

## WebSocket API

Exposed via `EvaluationService`:

```python
# service/evaluation_service.py

from codegen import ws_service, ws_expose, ws_type
from core.evaluation.analysis_service import AnalysisService, AnalysisResult


@ws_service
class EvaluationService:
    """WebSocket API for evaluation operations."""

    def __init__(self, store, session_manager):
        self._analysis_service = AnalysisService(store, session_manager)

    @ws_expose
    async def analyze_session(
        self,
        session_id: str,
        backend_name: str | None = None,
    ) -> dict:
        """Run post-hoc LLM analysis on a session.

        Args:
            session_id: Session to analyze
            backend_name: Override analysis backend (default: configured local model)

        Returns:
            {"success": bool, "analysis": PostHocAnalysis | null, "error": str | null}
        """
        result = await self._analysis_service.analyze_session(session_id, backend_name)

        if result.success:
            return {
                "success": True,
                "analysis": self._serialize_analysis(result.analysis),
                "error": None,
            }
        else:
            return {
                "success": False,
                "analysis": None,
                "error": result.error,
            }

    @ws_expose
    async def get_session_analyses(self, session_id: str) -> list[dict]:
        """Get all analyses for a session."""
        analyses = await self._store.get_post_hoc_analyses(session_id)
        return [self._serialize_analysis(a) for a in analyses]
```

## Configuration

```yaml
# In config.yaml

evaluation:
  enabled: true

  analysis:
    # Backend for LLM analysis - use a local model to avoid API costs
    # Must be defined in top-level 'backends' section
    backend: ollama

    # Temperature for analysis (lower = more consistent JSON)
    temperature: 0.3

    # Timeout for analysis completion
    timeout_seconds: 120

# Example local backend configuration
backends:
  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    api_key: ollama
    model: llama3.2:70b  # Or whatever you have
```

## Usage Patterns

### Manual Trigger (UI)

```typescript
// React component
const analyzeSession = async (sessionId: string) => {
  setLoading(true);
  try {
    const result = await rpc.call("analyzeSession", { session_id: sessionId });
    if (result.success) {
      setAnalysis(result.analysis);
    } else {
      showError(result.error);
    }
  } finally {
    setLoading(false);
  }
};
```

### Batch Analysis (CLI)

```python
# scripts/batch_analyze.py
import asyncio
from core.evaluation.analysis_service import AnalysisService

async def analyze_all_sessions():
    service = AnalysisService(store, session_manager)
    sessions = await store.list_sessions()

    for session in sessions:
        # Skip already-analyzed sessions
        existing = await store.get_post_hoc_analyses(session.id)
        if existing:
            continue

        print(f"Analyzing {session.id}: {session.title}")
        result = await service.analyze_session(session.id)

        if result.success:
            print(f"  Score summary: {result.analysis.summary}")
        else:
            print(f"  Error: {result.error}")

        # Rate limit for local models
        await asyncio.sleep(1)

asyncio.run(analyze_all_sessions())
```

## Model Selection Considerations

### Recommended Local Models

| Model | Context | Speed | JSON Reliability | Notes |
|-------|---------|-------|-----------------|-------|
| Llama 3.2 70B | 128K | Slow | Excellent | Best quality, needs good GPU |
| Llama 3.2 8B | 128K | Fast | Good | Good balance for most uses |
| Qwen2.5 32B | 128K | Medium | Excellent | Great at following JSON format |
| Mistral 7B | 32K | Fast | Fair | May need prompt tweaking |

### JSON Reliability Tips

1. **Use low temperature** (0.2-0.4) for more consistent output
2. **Repeat format in prompt** - show the JSON schema clearly
3. **Add "Respond with ONLY JSON"** to system prompt
4. **Handle recovery gracefully** - strip fences, fix trailing commas
5. **Log failures** for prompt iteration

## Summary

The post-hoc analysis service provides a clean pipeline for evaluating sessions with local LLMs:

1. **Context Gathering** - Loads all relevant data (session, markers, flags)
2. **Prompt Building** - Renders Jinja2 template with full context
3. **Local Model Completion** - Sends to ollama/llamacpp via OpenAI-compatible API
4. **Response Parsing** - Extracts structured JSON with error recovery
5. **Storage** - Persists analysis for later querying and export

Key design decisions:
- **Local models preferred** - Saves API costs, latency acceptable for batch ops
- **Single-shot completion** - No tool calling needed, simpler and more reliable
- **Structured JSON output** - Easy to parse and aggregate
- **Graceful error handling** - Recovery from common JSON issues
- **Correlation with markers** - Analysis specifically looks at how automatic markers relate to quality
