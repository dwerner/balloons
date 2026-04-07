# PLAN: Model Evaluation Framework

**Spec Version:** 0.1.0
**Status:** Draft
**Created:** 2025-04-06

## Overview

A comprehensive framework for empirically measuring model behaviors across sessions. Combines automatic detection, manual flagging, and post-hoc LLM analysis to build a dataset for model comparison and prompt optimization.

### Design Principles

1. **Post-hoc focused** - Most analysis runs after sessions complete, not real-time
2. **Full data retention** - Private app, no privacy constraints on storing messages
3. **Single-user stats** - No multi-tenant aggregation complexity
4. **Custom dashboard** - Analysis/visualization built separately, this provides data

### Goals

1. **Automatic behavior markers** - Programmatic detection of patterns (write_without_read, etc.)
2. **User sentiment markers** - Detect frustration/satisfaction in user messages
3. **Manual turn flagging** - User-initiated ratings and annotations
4. **Stop event tracking** - Record why/how responses ended
5. **Post-hoc LLM analysis** - Rubric-based evaluation after sessions
6. **Data export** - Clean data for custom analysis dashboards

---

## Part 1: Existing Infrastructure

### Already Implemented

| Component | Location | Status |
|-----------|----------|--------|
| `Sentiment` enum | `models.py:23` | `excellent/good/review/poor/terrible` |
| `Turn.sentiment` field | `models.py:798` | Storage works, no UI |
| `TurnData.sentiment` | `storage_schema.py:53` | Rust schema complete |
| `ReviewData` schema | `storage_schema.py:147` | Full rubric + task categorization |
| Review agent prompt | `prompts/review-agent.md` | Guides rubric collection |
| `save_review` tool | `core/tool_executor.py:1113` | Stores review data |
| `:review` command | `core/commands.py:379` | Creates review fork |

### Missing (This Plan Adds)

- Turn sentiment UI (buttons on turns)
- Custom turn flags/annotations
- Automatic behavior detection
- Automatic user sentiment detection
- Stop event tracking
- Post-hoc LLM analysis service
- Data export for external analysis

---

## Part 2: Data Model

### BehaviorMarker (Automatic Model Behaviors)

```python
@rust_schema
@dataclass
class BehaviorMarker:
    """Automatically detected model behavior pattern."""
    id: str  # UUID
    marker_type: str  # "write_without_read", "apologetic_retry", etc.
    category: str  # "tool_usage", "frustration", "quality", "communication"

    # Location
    session_id: str
    exchange_id: str
    turn_ids: list[str]  # Turns involved

    # Detection info
    severity: str  # "info", "warning", "error"
    confidence: float  # 0.0-1.0
    details: dict  # Marker-specific data (file paths, snippets, etc.)

    # Context
    backend_name: str
    model_name: str
    detected_at: str  # ISO 8601
```

### UserSentimentMarker (Automatic User Sentiment)

```python
@rust_schema
@dataclass
class UserSentimentMarker:
    """Detected sentiment in user messages."""
    id: str  # UUID
    marker_type: str  # "user_frustrated", "user_confused", "user_correcting", etc.
    category: str  # "positive", "negative", "neutral"

    # Location
    session_id: str
    turn_id: str
    exchange_id: str

    # Evidence
    confidence: float  # 0.0-1.0
    matched_pattern: str  # Regex/phrase that matched
    snippet: str  # Relevant text from message

    # Context
    backend_name: str
    model_name: str
    detected_at: str  # ISO 8601
```

### TurnFlag (Manual User Annotations)

```python
@rust_schema
@dataclass
class TurnFlag:
    """User-created flag/annotation on a turn."""
    id: str  # UUID
    turn_id: str
    session_id: str

    flag_type: str  # "bug", "hallucination", "great", "wrong_tool", "verbose", "custom"
    note: str = ""  # Optional annotation text

    created_at: str  # ISO 8601
```

### StopEvent (How Responses Ended)

```python
@rust_schema
@dataclass
class StopEvent:
    """Record of how a streaming response ended."""
    id: str  # UUID
    session_id: str
    exchange_id: str

    stop_type: str  # "user_cancelled", "timeout", "rate_limited", "truncated", "json_error", "api_error", "tool_loop"
    severity: str  # "info", "warning", "error"

    # Metrics at stop time
    turn_count: int
    tool_count: int
    tokens_streamed: int
    duration_ms: int

    # Details
    error_message: str = ""
    partial_content: str = ""  # Last N chars before stop

    # Context
    backend_name: str = ""
    model_name: str = ""
    occurred_at: str = ""  # ISO 8601
```

### PostHocAnalysis (LLM Evaluation)

```python
@rust_schema
@dataclass
class PostHocAnalysis:
    """LLM-generated post-hoc analysis of a session."""
    id: str  # UUID
    session_id: str
    analysis_backend: str

    # LLM-assigned rubric scores with reasoning
    scores: dict  # {"correctness": {"score": 4, "reasoning": "..."}, ...}

    # Analysis sections
    pattern_analysis: str  # What patterns LLM observed
    marker_correlation: str  # How markers relate to issues
    recommendations: str  # What could improve
    summary: str  # 2-3 sentence summary

    # Metadata
    generated_at: str  # ISO 8601

    # Link to user review if exists
    user_review_id: Optional[str] = None
```

---

## Part 3: Behavior Markers (Automatic Detection)

### Marker Types

#### Tool Usage Patterns

| Marker | Description | Detection |
|--------|-------------|-----------|
| `write_without_read` | Writes file not in context | Track Read vs Write/Edit paths |
| `redundant_read` | Re-reads already-read file | Duplicate file paths in exchange |
| `glob_without_read` | Globs but doesn't read results | Glob results vs Read calls |
| `excessive_tools` | >N tool calls in exchange | Configurable threshold (default 25) |
| `tool_error_loop` | Same tool fails repeatedly | Track consecutive failures |
| `parallel_missed` | Sequential calls could be parallel | Detect independent operations |

#### Model Frustration Indicators

| Marker | Description | Detection |
|--------|-------------|-----------|
| `apologetic_retry` | "I apologize", "Let me try again" | Regex patterns |
| `confusion_indicator` | "I'm not sure", "unclear" | Regex patterns |
| `self_correction` | "Actually", "Wait", "On second thought" | Regex patterns |
| `repeated_approach` | Same failing approach multiple times | Hash approach signatures |
| `excessive_caveats` | Overuses hedging language | Frequency threshold |

#### Quality Indicators (Positive)

| Marker | Description | Detection |
|--------|-------------|-----------|
| `first_attempt_success` | Task done without retry | No errors in exchange |
| `code_runs_first_try` | Bash returns 0 first time | Check exit codes |
| `proactive_verification` | Verifies own work | Detects test runs after changes |

### Detector Architecture

```python
class BaseDetector(ABC):
    """Base class for behavior detectors."""

    @property
    @abstractmethod
    def detector_id(self) -> str: ...

    @property
    @abstractmethod
    def category(self) -> str: ...

    @abstractmethod
    def analyze(self, ctx: DetectorContext) -> Iterator[BehaviorMarker]: ...

@dataclass
class DetectorContext:
    """Context for post-hoc analysis of an exchange."""
    session_id: str
    exchange_id: str
    backend_name: str
    model_name: str

    # All turns in exchange
    turns: list[Turn]

    # Extracted data
    tool_calls: list[ToolUseBlock]
    tool_results: list[ToolResultBlock]
    text_blocks: list[TextBlock]

    # File tracking
    files_read: set[str]
    files_written: set[str]
    files_globbed: set[str]
```

### Example Detector

```python
class WriteWithoutReadDetector(BaseDetector):
    @property
    def detector_id(self) -> str:
        return "write_without_read"

    @property
    def category(self) -> str:
        return "tool_usage"

    def analyze(self, ctx: DetectorContext) -> Iterator[BehaviorMarker]:
        for tool in ctx.tool_calls:
            if tool.name in ("Write", "Edit"):
                file_path = tool.input.get("file_path", "")
                if file_path and file_path not in ctx.files_read:
                    yield BehaviorMarker(
                        id=str(uuid.uuid4()),
                        marker_type=self.detector_id,
                        category=self.category,
                        session_id=ctx.session_id,
                        exchange_id=ctx.exchange_id,
                        turn_ids=[...],
                        severity="warning",
                        confidence=1.0,
                        details={"file_path": file_path, "tool": tool.name},
                        backend_name=ctx.backend_name,
                        model_name=ctx.model_name,
                        detected_at=datetime.now().isoformat(),
                    )
```

---

## Part 4: User Sentiment Detection

### Marker Types

| Marker | Category | Example Patterns |
|--------|----------|------------------|
| `user_frustrated` | negative | "doesn't work", "still broken", "I already told you" |
| `user_confused` | negative | "I don't understand", "what do you mean", "huh?" |
| `user_correcting` | negative | "No, I meant", "that's not what I asked", "wrong" |
| `user_repeating` | negative | Similar request within 3 turns (70%+ similarity) |
| `user_escalating` | negative | Caps, expletives, urgency markers |
| `user_satisfied` | positive | "Perfect", "exactly", "thanks", "great" |
| `user_acknowledging` | positive | "Got it", "makes sense", "understood" |

### Detection Approach

Post-hoc regex scanning of user turns:

```python
class UserSentimentDetector:
    PATTERNS = {
        "user_frustrated": {
            "category": "negative",
            "patterns": [
                r"(doesn't|does not|won't|will not) (work|run|compile)",
                r"still (broken|not working|failing)",
                r"I('ve| have) (already|just) (told|said|asked)",
            ],
            "confidence": 0.8,
        },
        "user_confused": {
            "category": "negative",
            "patterns": [
                r"I (don't|do not) understand",
                r"what (do you|does that) mean",
                r"(confused|confusing)",
            ],
            "confidence": 0.7,
        },
        # ... more patterns
    }

    def analyze_session(self, session: Session) -> list[UserSentimentMarker]:
        markers = []
        for turn in session.turns:
            if turn.role == "user":
                markers.extend(self._analyze_turn(turn, session))
        return markers
```

### Repetition Detection

```python
def detect_repetition(self, user_turns: list[Turn]) -> list[UserSentimentMarker]:
    """Detect when user repeats similar requests."""
    markers = []
    for i, current in enumerate(user_turns[1:], 1):
        for prev in user_turns[max(0, i-3):i]:
            similarity = self._jaccard_similarity(
                self._get_text(current),
                self._get_text(prev)
            )
            if similarity > 0.7:
                markers.append(UserSentimentMarker(
                    marker_type="user_repeating",
                    category="negative",
                    confidence=similarity,
                    snippet=f"Similar to: {self._get_text(prev)[:100]}",
                    ...
                ))
    return markers
```

---

## Part 5: Manual Turn Flagging

### Sentiment UI (Existing Enum)

Add buttons to assistant turns for existing `Sentiment` values:

```
❤️ Excellent  |  👍 Good  |  🔍 Review  |  👎 Poor  |  ☠️ Terrible
```

### Custom Flags

Beyond sentiment, allow custom flags:

| Flag Type | Emoji | Description |
|-----------|-------|-------------|
| `bug` | 🐛 | Bug/Error in output |
| `hallucination` | 💭 | Made something up |
| `great` | ⭐ | Great example to keep |
| `wrong_tool` | 🔧 | Wrong tool choice |
| `verbose` | 📜 | Too verbose |
| `terse` | 🔇 | Too terse |
| `custom` | 🏷️ | Custom with note |

### Service API

```python
@ws_expose
async def set_turn_sentiment(
    self,
    session_id: str,
    turn_id: str,
    sentiment: str | None,  # "excellent", "good", "review", "poor", "terrible", or None
) -> bool:
    """Set or clear sentiment rating on a turn."""
    ...

@ws_expose
async def add_turn_flag(
    self,
    session_id: str,
    turn_id: str,
    flag_type: str,
    note: str = "",
) -> TurnFlag:
    """Add a custom flag to a turn."""
    ...

@ws_expose
async def remove_turn_flag(
    self,
    flag_id: str,
) -> bool:
    """Remove a flag."""
    ...

@ws_expose
async def get_session_flags(
    self,
    session_id: str,
) -> list[TurnFlag]:
    """Get all flags for a session."""
    ...
```

---

## Part 6: Stop Event Tracking

### Stop Types

| Type | Severity | Trigger |
|------|----------|---------|
| `user_cancelled` | info | User clicked stop |
| `timeout` | warning | Response exceeded time limit |
| `rate_limited` | warning | API rate limit hit |
| `truncated` | warning | Max tokens reached |
| `json_error` | error | Malformed JSON in response |
| `api_error` | error | API returned error |
| `tool_loop` | warning | Circuit breaker triggered |

### Integration

Hook into existing `InterruptionBlock` and `ErrorBlock` creation:

```python
# In core/runner.py or streaming.py

async def _handle_stream_end(self, reason: str, ctx: StreamContext):
    """Record stop event when stream ends abnormally."""
    if reason == "done":
        return  # Normal completion, no stop event

    stop_event = StopEvent(
        id=str(uuid.uuid4()),
        session_id=ctx.session_id,
        exchange_id=ctx.exchange_id,
        stop_type=self._map_reason(reason),
        severity=self._get_severity(reason),
        turn_count=ctx.turn_count,
        tool_count=ctx.tool_count,
        tokens_streamed=ctx.output_tokens,
        duration_ms=ctx.duration_ms,
        error_message=ctx.error_message or "",
        backend_name=ctx.backend_name,
        model_name=ctx.model_name,
        occurred_at=datetime.now().isoformat(),
    )
    await self._store.save_stop_event(stop_event)
```

---

## Part 7: Post-Hoc LLM Analysis

> **Deep Dive:** See [docs/analysis-service-deep-dive.md](docs/analysis-service-deep-dive.md) for full implementation details.

### Why Local Models

Analysis is ideal for local models:
1. **No tool calling** - Just structured JSON output
2. **Latency tolerance** - Can take 30-60s without impacting UX
3. **Bounded context** - Session + markers fits in context window
4. **Cost savings** - Avoid API costs for high-volume analysis
5. **Privacy** - Keep session data local

### Recommended Local Models

| Model | Context | Speed | JSON Reliability |
|-------|---------|-------|-----------------|
| Llama 3.2 70B | 128K | Slow | Excellent |
| Qwen2.5 32B | 128K | Medium | Excellent |
| Llama 3.2 8B | 128K | Fast | Good |

### Analysis Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│  1. ContextGatherer.gather(session_id)                      │
│     → Loads session, markers, flags, stop events            │
├─────────────────────────────────────────────────────────────┤
│  2. PromptBuilder.build(context)                            │
│     → Renders Jinja2 template with all data                 │
├─────────────────────────────────────────────────────────────┤
│  3. LocalModelClient.complete(prompt, backend)              │
│     → Sends to ollama/llamacpp via OpenAI-compatible API    │
├─────────────────────────────────────────────────────────────┤
│  4. ResponseParser.parse(response)                          │
│     → Validates JSON, extracts scores/analysis              │
├─────────────────────────────────────────────────────────────┤
│  5. Store.save_analysis(PostHocAnalysis)                    │
│     → Persists to LMDB                                      │
└─────────────────────────────────────────────────────────────┘
```

### Service API

```python
@ws_expose
async def analyze_session(
    self,
    session_id: str,
    backend_name: str | None = None,  # Override configured backend
) -> dict:
    """Run LLM-assisted post-hoc analysis of a session.

    Returns:
        {"success": bool, "analysis": PostHocAnalysis | null, "error": str | null}
    """
```

### JSON Response Format

The analysis prompt requests this exact JSON structure:

```json
{
  "scores": {
    "correctness": {"score": 4, "reasoning": "..."},
    "efficiency": {"score": 3, "reasoning": "..."},
    "instruction_following": {"score": 5, "reasoning": "..."},
    "recovery": {"score": 4, "reasoning": "..."},
    "autonomy": {"score": 4, "reasoning": "..."},
    "judgment": {"score": 3, "reasoning": "..."},
    "communication": {"score": 4, "reasoning": "..."}
  },
  "pattern_analysis": "What patterns across markers and sentiment",
  "marker_correlation": "How automatic markers relate to actual issues",
  "key_moments": ["critical moment 1", "critical moment 2"],
  "recommendations": "What could improve similar sessions",
  "summary": "2-3 sentence overall assessment"
}
```

**Tips for reliable JSON output:**
- Use low temperature (0.3) for consistency
- Include "Respond with ONLY JSON" in system prompt
- Parser handles markdown fences and trailing commas
- Log failures for prompt iteration

---

## Part 8: Data Export

### Export Service

```python
@ws_expose
async def export_session_evaluation_data(
    self,
    session_id: str,
) -> dict:
    """Export all evaluation data for a session as JSON."""
    return {
        "session_id": session_id,
        "session_metadata": await self._get_session_metadata(session_id),
        "turns": await self._get_turns_with_sentiment(session_id),
        "behavior_markers": await self._store.get_behavior_markers(session_id),
        "user_sentiment_markers": await self._store.get_user_sentiment_markers(session_id),
        "stop_events": await self._store.get_stop_events(session_id),
        "turn_flags": await self._store.get_turn_flags(session_id),
        "reviews": await self._store.get_reviews(session_id),
        "analyses": await self._store.get_analyses(session_id),
    }

@ws_expose
async def export_all_evaluation_data(
    self,
    since: str | None = None,  # ISO 8601 timestamp
) -> dict:
    """Export all evaluation data for analysis dashboard."""
    return {
        "exported_at": datetime.now().isoformat(),
        "sessions": await self._export_all_sessions(since),
        "aggregate_stats": await self._compute_aggregates(),
    }
```

### Aggregate Stats

```python
async def _compute_aggregates(self) -> dict:
    """Compute aggregate statistics for dashboard."""
    return {
        "by_model": {
            "claude-sonnet": {
                "session_count": 42,
                "avg_scores": {"correctness": 4.2, ...},
                "marker_rates": {"write_without_read": 0.15, ...},
                "user_satisfaction_rate": 0.85,
            },
            ...
        },
        "by_task_category": {
            "debugging": {"session_count": 15, ...},
            "feature": {"session_count": 20, ...},
            ...
        },
        "trends": {
            "weekly_scores": [...],
            "weekly_marker_rates": [...],
        },
    }
```

---

## Part 9: Storage

### LMDB Tables

```rust
// Behavior markers (automatic)
BEHAVIOR_MARKERS        // Key: marker_id, Value: BehaviorMarker
BEHAVIOR_BY_SESSION     // Key: session_id, Value: [marker_ids]

// User sentiment markers (automatic)
USER_SENTIMENT_MARKERS      // Key: marker_id, Value: UserSentimentMarker
USER_SENTIMENT_BY_SESSION   // Key: session_id, Value: [marker_ids]

// Stop events
STOP_EVENTS             // Key: event_id, Value: StopEvent
STOP_EVENTS_BY_SESSION  // Key: session_id, Value: [event_ids]

// Turn flags (manual)
TURN_FLAGS              // Key: flag_id, Value: TurnFlag
TURN_FLAGS_BY_SESSION   // Key: session_id, Value: [flag_ids]
TURN_FLAGS_BY_TURN      // Key: turn_id, Value: [flag_ids]

// Post-hoc analyses
POST_HOC_ANALYSES       // Key: analysis_id, Value: PostHocAnalysis
ANALYSES_BY_SESSION     // Key: session_id, Value: [analysis_ids]
```

---

## Part 10: Module Layout

```
core/
├── evaluation/
│   ├── __init__.py
│   ├── detector_context.py      # DetectorContext dataclass
│   ├── base_detector.py         # BaseDetector ABC
│   ├── behavior_detectors.py    # Tool usage, frustration detectors
│   ├── user_sentiment.py        # User sentiment detection
│   ├── analysis_service.py      # Post-hoc LLM analysis
│   └── export.py                # Data export functions
│
storage_schema.py                # Add new schemas
service/
├── evaluation_service.py        # WebSocket-exposed evaluation API
```

---

## Part 11: Configuration

```yaml
evaluation:
  enabled: true

  # Behavior detection (post-hoc)
  behavior_detection:
    detectors:
      write_without_read: {enabled: true, severity: warning}
      redundant_read: {enabled: true, severity: info}
      excessive_tools: {enabled: true, threshold: 25}
      tool_error_loop: {enabled: true, threshold: 3}
      apologetic_retry: {enabled: true}
      confusion_indicator: {enabled: true}
      self_correction: {enabled: true}

  # User sentiment detection (post-hoc)
  user_sentiment_detection:
    enabled: true
    repetition_threshold: 0.7  # Jaccard similarity for user_repeating

  # Stop event tracking (real-time)
  stop_tracking:
    enabled: true

  # Post-hoc LLM analysis
  analysis:
    # Backend for analysis - use local model to avoid API costs
    # Must be defined in top-level 'backends' section
    backend: ollama

    # Temperature for analysis (lower = more consistent JSON)
    temperature: 0.3

    # Timeout for analysis completion (seconds)
    timeout_seconds: 120

# Example local backend for analysis
backends:
  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    api_key: ollama
    model: llama3.2:70b  # Or qwen2.5:32b, llama3.2:8b, etc.
```

---

## Part 12: Implementation Order

### Phase 1: Manual Flagging (Foundation)
1. Add `set_turn_sentiment` RPC to service
2. Add `TurnFlag` schema + storage
3. Add flag RPCs (`add_turn_flag`, `remove_turn_flag`, `get_session_flags`)
4. UI: Sentiment buttons on turns
5. UI: Flag menu on turns

### Phase 2: Stop Event Tracking
1. Add `StopEvent` schema + storage
2. Hook into stream end handling
3. Surface in UI (optional indicator on exchanges)

### Phase 3: Behavior Detection
1. Add `BehaviorMarker` schema + storage
2. Create `DetectorContext` builder
3. Implement core detectors (write_without_read, tool_error_loop, etc.)
4. Create detection runner (runs post-hoc on exchange completion)

### Phase 4: User Sentiment Detection
1. Add `UserSentimentMarker` schema + storage
2. Implement pattern-based detection
3. Implement repetition detection
4. Create detection runner

### Phase 5: Post-Hoc Analysis
1. Add `PostHocAnalysis` schema + storage
2. Create analysis prompt template
3. Implement `analyze_session` service method
4. UI: Trigger analysis from session context menu

### Phase 6: Export & Dashboard Foundation
1. Implement `export_session_evaluation_data`
2. Implement `export_all_evaluation_data`
3. Implement aggregate computation
4. Document JSON schemas for dashboard consumption

---

## Open Questions

1. **Detection timing** - Run behavior detection on exchange completion, session save, or explicit trigger?
   - Recommendation: On exchange completion (background task)

2. **Analysis trigger** - Auto-analyze after sessions with many negative markers?
   - Recommendation: Manual trigger only for now, auto-suggest later

3. **Flag persistence** - Should flags survive archive operations?
   - Recommendation: Yes, store flags separately from turns

4. **Export format** - JSON sufficient or need CSV/Parquet for analysis tools?
   - Recommendation: JSON primary, add CSV export if needed

---

## Success Metrics

1. All sessions have behavior/user-sentiment markers computed
2. >50% of significant sessions have manual sentiment ratings
3. Post-hoc analysis correlates with manual ratings (>0.7 correlation)
4. Export data enables meaningful model comparison in dashboard
