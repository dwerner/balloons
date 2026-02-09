# Plan: Session Quality Review System

**Spec Version:** 0.1.0
**Status:** Draft
**Created:** 2025-02-09

## Overview

A methodology and feature for evaluating LLM performance in Balloons sessions. Enables subjective quality tracking with structured rubrics, producing data for longitudinal analysis across models, prompts, and task types.

### Goals

1. **Minimal friction during work** — quick sentiment markers on turns, nothing more
2. **Structured post-session review** — rubric-based scoring at user's leisure
3. **Dual-perspective analysis** — user scores + separate analysis LLM commentary
4. **Longitudinal data** — stored reviews for reporting and comparison

---

## Workflow

### 1. During Session: Turn Sentiment Marking

Users can mark LLM response turns (not tool calls, not user inputs) with a 5-point sentiment scale:

| Marker | Meaning |
|--------|---------|
| ❤️ | Excellent — notably good |
| 👍 | Good — worked as expected |
| 🔍 | Neutral — mark for review (no judgment, just "look at this later") |
| 👎 | Poor — didn't work well |
| ☠️ | Terrible — actively harmful/wrong |

**UI:** Sentiment buttons appear on assistant turns in the chat log. Clicking sets/changes the marker. Markers persist with the turn.

**Storage:** Single `sentiment` field on the Turn, nullable. Values: `"excellent"`, `"good"`, `"review"`, `"poor"`, `"terrible"`, or `null`.

### 2. Initiating Review: `:review` Command

User runs `:review` to initiate a quality review of the current session.

**Flow:**
1. Creates a fork with the session context
2. Hands off to the configured **review backend** (may be different model/provider)
3. Review agent guides user through the rubric
4. User provides scores and summary
5. Analysis LLM provides commentary (after user input, to avoid bias)
6. Review data saved via custom tool call

### 3. Review Rubric

User scores each dimension 1-5:

| Dimension | Description |
|-----------|-------------|
| **Correctness** | Did outputs work? Factually/technically right? |
| **Efficiency** | Direct path or meandering? Wasted effort? |
| **Instruction Following** | Did it do what you asked? |
| **Recovery** | How well did it handle/fix mistakes? |
| **Autonomy** | Worked independently vs needed hand-holding? |
| **Judgment** | Good decisions when you didn't specify? |
| **Communication** | Clear, right level of detail? |

**Scale:**
- 1 = Very poor
- 2 = Poor
- 3 = Adequate
- 4 = Good
- 5 = Excellent

### 4. Task Categorization

The analysis LLM classifies the session with:

**Task category** (enum v0.1):
- `debugging` — Fixing bugs, investigating issues
- `feature` — Building new functionality
- `refactor` — Restructuring existing code
- `exploration` — Research, spikes, figuring out approach
- `documentation` — Writing docs, comments, specs
- `review` — Code review, PR review
- `learning` — Understanding code, concepts
- `ops` — Deployment, infra, config
- `other` — Catch-all (user provides description)

**Task description:** 1-sentence freeform description of what the session was about.

### 5. Analysis LLM Commentary

After user provides scores and summary, the analysis LLM:
- Summarizes patterns from sentiment markers (❤️👍🔍👎☠️)
- Identifies potential issues not explicitly flagged
- Notes whether user scores align with what it observes
- Suggests what could have improved the session

---

## Data Model

### Turn Sentiment (modification to TurnData)

Add to `TurnData`:

```python
sentiment: Optional[str] = None  # "excellent", "good", "review", "poor", "terrible"
```

### Review Record

New table: `REVIEWS`

```python
@rust_schema
@dataclass
class ReviewData:
    """Quality review of a session."""
    id: str  # UUID
    session_id: str  # Session being reviewed
    reviewed_at: str  # ISO 8601 timestamp

    # What was being evaluated
    model_under_review: str  # Backend name active during session
    review_backend: str  # Backend that performed the analysis

    # User-provided rubric scores (1-5)
    score_correctness: int
    score_efficiency: int
    score_instruction_following: int
    score_recovery: int
    score_autonomy: int
    score_judgment: int
    score_communication: int

    # Task categorization
    task_category: str  # enum value from categories list
    task_description: str  # freeform 1-sentence

    # Summaries
    user_summary: str  # User's freeform comments
    llm_commentary: str  # Analysis LLM's commentary

    # Metadata
    spec_version: str = "0.1.0"  # Version of this spec used
    session_duration_minutes: Optional[int] = None  # Optional
    turn_count: int = 0  # Number of turns in session
    sentiment_counts: dict = field(default_factory=dict)  # {"excellent": 2, "poor": 1, ...}
```

---

## Configuration

### Review Backend Setting

Add to `config.yaml`:

```yaml
# Backend to use for session quality reviews
# Must be a configured backend name
review_backend: openrouter

backends:
  openrouter:
    type: openai
    model: anthropic/claude-sonnet-4
    # ...
```

Add to `Config` dataclass:

```python
review_backend: Optional[str] = None  # Backend name for reviews, defaults to default_backend
```

If `review_backend` is not set, uses `default_backend`.

---

## Commands

### `:review`

Initiates a quality review of the current session.

**Behavior:**
1. Validates `review_backend` is configured
2. Creates a fork with:
   - Session context (turns with sentiment markers visible)
   - Review system prompt (see below)
3. Switches to review backend
4. Review agent guides user through rubric
5. Saves review data on completion

### Future: `:reviews`

List/browse saved reviews (not in v0.1).

---

## Review Agent System Prompt

```markdown
You are a session quality review agent. Your job is to help the user evaluate the quality of an LLM session they just completed.

## Context

You have access to the full conversation history of the session being reviewed. Some turns may have sentiment markers:
- ❤️ Excellent
- 👍 Good
- 🔍 Mark for review
- 👎 Poor
- ☠️ Terrible

## Your Task

1. **Collect rubric scores** — Ask the user to rate each dimension 1-5:
   - Correctness
   - Efficiency
   - Instruction Following
   - Recovery
   - Autonomy
   - Judgment
   - Communication

2. **Collect user summary** — Ask for their overall thoughts on the session.

3. **Classify the task** — Based on the conversation, determine:
   - Task category: debugging, feature, refactor, exploration, documentation, review, learning, ops, or other
   - Task description: 1 sentence describing what the session was about

4. **Provide your analysis** — After the user provides their scores and summary:
   - Summarize patterns from sentiment markers
   - Note any issues you observed that weren't flagged
   - Comment on whether scores align with what you see
   - Suggest what could have improved the session

5. **Save the review** — Call the `save_review` tool with all collected data.

## Guidelines

- Be efficient — don't over-explain
- Accept scores in any format (list, one at a time, etc.)
- Your analysis comes AFTER user input to avoid biasing them
- Be honest but constructive in your analysis
```

---

## Tool: `save_review`

Custom Balloons tool for saving review data:

```json
{
  "name": "save_review",
  "description": "Save the completed session quality review",
  "parameters": {
    "session_id": "string (required) - ID of session being reviewed",
    "model_under_review": "string (required) - Backend name of model being evaluated",
    "scores": {
      "correctness": "int 1-5",
      "efficiency": "int 1-5",
      "instruction_following": "int 1-5",
      "recovery": "int 1-5",
      "autonomy": "int 1-5",
      "judgment": "int 1-5",
      "communication": "int 1-5"
    },
    "task_category": "string - one of: debugging, feature, refactor, exploration, documentation, review, learning, ops, other",
    "task_description": "string - 1 sentence description",
    "user_summary": "string - user's freeform comments",
    "llm_commentary": "string - your analysis"
  }
}
```

---

## UI Changes

### Chat Log: Sentiment Buttons

On assistant turns (TextBlock responses only, not tool calls):

```
┌─────────────────────────────────────────────────────┐
│ [Assistant]                          ❤️ 👍 🔍 👎 ☠️ │
│                                                     │
│ Here's the implementation...                        │
│                                                     │
└─────────────────────────────────────────────────────┘
```

- Buttons appear on hover or always visible (TBD)
- Active sentiment is highlighted
- Clicking toggles (click same = clear, click different = change)

### Status Bar (during review)

Show review mode indicator:

```
[review:sonnet] Reviewing session "fix-auth-bug"
```

---

## Files to Modify

| File | Changes |
|------|---------|
| `config.py` | Add `review_backend` field to Config |
| `models.py` | Add `sentiment` field to Turn dataclass |
| `storage_schema.py` | Add `sentiment` to TurnData, add ReviewData |
| `session.py` | Add `:review` command handler |
| `app.py` | Handle review fork creation, tool registration |
| `widgets/chat_log.py` | Add sentiment buttons to assistant turns |
| `prompts/review-agent.md` | Review agent system prompt |
| `config/config.sample.yaml` | Document `review_backend` setting |

---

## Reporting (Future)

Not in v0.1, but the data model supports:

- **Radar charts** — Multi-dimension polygon plot of rubric scores
- **Bar charts** — Compare scores across sessions/models
- **Trends** — Track dimension scores over time
- **Filtering** — By model, task category, date range
- **Aggregation** — Average scores per model, per task type

---

## Versioning

### Spec Version: 0.1.0

Changes to this spec should increment the version:
- **Patch (0.1.x):** Clarifications, typo fixes
- **Minor (0.x.0):** New optional fields, new task categories
- **Major (x.0.0):** Breaking changes to data model, rubric dimensions

Reviews store the spec version used, enabling migration if needed.

### Task Categories Versioning

Categories may be added in future versions. Existing reviews retain their original category values. New categories:
- Added in minor version bumps
- Old reviews remain valid
- UI/reporting gracefully handles unknown categories

---

## Open Questions

1. **Sentiment button visibility** — Always visible or hover-to-reveal?
2. **Review fork behavior** — Does it merge back, or stay separate?
3. **Multi-model sessions** — How to handle if user switched backends mid-session?
4. **Partial reviews** — What if user abandons review before completing?

---

## Implementation Order

1. **Turn sentiment storage** — Add field to Turn/TurnData
2. **UI: Sentiment buttons** — Add to chat log widget
3. **Config: review_backend** — Add config field
4. **Review data model** — Add ReviewData, storage
5. **`:review` command** — Create fork, switch backend
6. **Review agent prompt** — Write system prompt
7. **`save_review` tool** — Implement custom tool
8. **Integration** — Wire it all together
