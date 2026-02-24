# Journeyman: Agent-Tutor Methodology

*A conceptual document preserving the vision and key learnings from the Journeyman project (January 2026), an exploration of agent-driven tutoring with stateful knowledge tracking.*

## Vision

An AI agent that teaches humans with **measurable, persistent progress** - not through hidden algorithms, but through **transparent methodology** where the learner sees and understands the same metrics the system uses.

The core insight: treating knowledge acquisition as a **first-class data structure** (a graph with typed nodes, edges representing dependencies, and probabilistic confidence estimates) enables principled decisions about what to teach, when to assess, and how to adapt.

---

## The Learning Cycle

### Structure: Orient → Assess → Teach → Practice → Reflect → Persist

**Orient** (Both agent and learner)
- Load current knowledge state
- Learner states intent: "What do you want to work on?"
- Show mastery status of relevant skills
- Surface items due for review
- Time since last session as context

**Assess** (Agent probes learner)
- If cold start (new topic): Single well-chosen probe at medium difficulty
- If resuming: Check retention
- Watch HOW they reason, not just if correct
- Wrong mental models are as informative as missing knowledge
- Update confidence using Bayesian Knowledge Tracing

**Teach** (Agent explains)
- Scope directly from what probe revealed
- Address the specific gap identified
- **Think aloud deliberately** - visible reasoning teaches process
- Connect to what learner already knows
- Explain why this is being taught now

**Practice** (Loop until mastery or branch)
- **Practice is a LOOP, not a single step**
- Give transfer tasks (NOT same example from teaching)
- Ask for reasoning BEFORE accepting answer
- Distinguish failure modes: didn't understand vs can't apply vs execution error
- Repeat until learner says "enough" or consistent success
- **Branching**: If prerequisite gap discovered, spawn child cycle

**Reflect** (Both)
- Summarize what changed this cycle
- Show before/after confidence
- Note gaps remaining
- Ask learner for their self-assessment

**Persist** (Agent)
- Update knowledge graph (status, confidence, evidence)
- Update queue with next actions
- Append session to history

---

## Core Principles

### 1. Methodology is Exposed, Not Hidden

The learner sees **raw metrics** - confidence scores, BKT parameters, mastery thresholds. No translation layer, no simplification. The learner develops intuition for these metrics through experience.

```yaml
learner_sees:
  - current mastery per skill (0.0-1.0)
  - prior and posterior confidence after each response
  - delta from this interaction
  - item difficulty
  - slip and guess rates
  - what this skill unlocks
```

### 2. Mastery is the Exit Condition

Not time spent. Not attempts made. **Consistent demonstration across contexts**.

```yaml
completion_model:
  complete_when:
    skill_mastery: ">= 0.85"
    stability: "consecutive correct at sufficient difficulty"
  failure_handling:
    penalty: none
    action: "update model, adjust teaching, retry"
  attempts:
    limit: none
    tracked: true  # learner sees as data, not judgment
```

### 3. Cycles Complete, Skills Persist

A **cycle** is a session - it ends when you stop working ("done for now", not "mastered forever").

A **skill** is persistent state that evolves across sessions. Skills can regress without practice - even "durable" fades eventually.

### 4. Transfer Tasks Test Understanding

Same-example practice tests **memory**. Transfer tasks test **understanding**.

```yaml
transfer_tasks:
  - apply to new inputs requiring the model
  - reason backwards from outcome to cause
  - explain to someone else
  - recognize in unfamiliar context
```

### 5. Branch, Don't Restart

When a prerequisite gap surfaces mid-cycle:
1. Note the gap
2. Spawn child cycle on the prerequisite
3. Parent marked "blocked on [branch]"
4. Child completes, returns summary
5. Parent resumes

Branches can spawn their own branches. The key is: do "just enough" to unblock, defer the rest.

### 6. One Probe is Enough for Cold Start

Self-assessment fails for faded/unfamiliar knowledge ("don't know what you don't know").

But self-assessment works for "never learned" (you know what you haven't been exposed to).

For cold start: one well-chosen medium-difficulty question reveals the level. Watch reasoning, not just correctness.

---

## The Knowledge Graph

### Node Types

| Type | Description | Example |
|------|-------------|---------|
| **concept** | Mental model, understanding | "discrete inheritance" |
| **skill** | Ability to do something | "applying BKT formula" |
| **rule** | If-then relationship | "AND probability = multiply" |
| **ability** | General capability | "basic arithmetic" |

### Node Statuses

| Status | Meaning |
|--------|---------|
| **queued** | Not yet started |
| **open** | Actively investigating |
| **blocked** | Waiting on prerequisite |
| **provisional** | Seems to work, not yet tested in transfer |
| **stable** | Consistent success across contexts |
| **durable** | Persists over time, real-world application |

Nodes can regress. Even "durable" fades without practice.

### Hierarchical Structure

```
subjects:
  subject:
    specializations:
      specialization:
        topics:
          topic:
            nodes:
              node-id:
                type: concept | skill | rule | ability
                status: queued | open | blocked | provisional | stable | durable
                confidence: 0.0-1.0
                evidence: [...]
                prereqs: [...]
                next_action: "..."
```

### Dependencies (Edges)

Cross-cutting relationships between nodes:

```yaml
dependencies:
  - from: methodology.learning-science.bkt-applied
    to: math.probability.and-multiply
    type: prereq
```

### Action Queue

Priority-ordered list of what to work on next:

```yaml
queue:
  - path: biology.genetics.discrete-inheritance
    action: "Transfer task with mammalian example"
    priority: 1
```

---

## Bayesian Knowledge Tracing (BKT)

### The Core Parameters

| Parameter | Meaning | Typical |
|-----------|---------|---------|
| **P(L₀)** | Initial mastery (prior) | varies |
| **P(T)** | Learn rate - probability of learning after practice | 0.1-0.3 |
| **P(S)** | Slip - error despite knowing | 0.1 |
| **P(G)** | Guess - correct despite not knowing | 0.25 |

### Question Type Affects Parameters

```yaml
question_types:
  true_false:
    p_guess: 0.5  # 50% chance of guessing binary
    p_slip: 0.1   # hard to mess up if you know
  multiple_choice_4:
    p_guess: 0.25  # 1/4 random chance
    p_slip: 0.1
  open_recall:
    p_guess: 0.15  # hard to guess specific fact
    p_slip: 0.1
  open_explain:
    p_guess: 0.10  # explaining "why" is hard to fake
    p_slip: 0.15   # can fumble explanation
  procedure:
    p_guess: 0.05  # multi-step nearly impossible to guess
    p_slip: 0.25   # many opportunities for error
  transfer:
    p_guess: 0.05  # novel application can't be guessed
    p_slip: 0.15
```

### Update Formulas

**After correct answer:**
```
P(L|correct) = P(L)(1-P(S)) / [P(L)(1-P(S)) + (1-P(L))P(G)]
```

**After incorrect answer:**
```
P(L|incorrect) = P(L)P(S) / [P(L)P(S) + (1-P(L))(1-P(G))]
```

**After partial answer (attenuated update):**
```
P(L|partial) = P(L) + (1-P(L)) * 0.5 * (P(L|correct) - P(L))
```

The `(1-P(L))` attenuation means: at low confidence, partial answers help you climb; at high confidence, partial barely moves the needle. You can't coast to mastery on partial answers alone.

### Cold Start Calibration

When confidence = 0.0, first probe calibrates initial P(L₀) based on response quality:

```yaml
cold_start:
  comprehensive_answer: 0.7-0.95  # detailed, nuanced
  solid_answer: 0.4-0.7           # correct with good reasoning
  minimal_correct: 0.2-0.4        # right answer, thin explanation
  partial: 0.1-0.3                # some understanding, gaps evident
```

---

## Rubric-Based Evaluation

For written responses, weighted rubrics provide granular evidence:

```yaml
rubric_example:
  - criterion: "Names at least 2 factors"
    weight: 0.4
  - criterion: "Explains mechanism"
    weight: 0.3
  - criterion: "Distinguishes related concepts"
    weight: 0.2
  - criterion: "Mentions practical implications"
    weight: 0.1
```

**Rubric score** = sum of weights for criteria met (0.0 to 1.0)

**Rubric visibility:**
- **Open** (scaffolded/practice): Learner sees criteria before answering
- **Closed** (assessment): Criteria private, tests authentic recall

**Mapping to BKT:**
- Positive evidence (score >= 0.3): modulated update toward correct
- Negative evidence (score < 0.3): treat as incorrect

---

## Authentic Assessment

### Evidence-Centered Design

| Model | Question |
|-------|----------|
| **Competency Model** | What skills are we tracking? |
| **Evidence Model** | What behaviors demonstrate those skills? |
| **Task Model** | What authentic tasks generate that evidence? |

### Declared Assessment (vs Stealth Assessment)

Original stealth assessment: hidden tracking for research purposes.

Our adaptation: **declared assessment** - same benefit (learning from real work) but with explicit user consent.

```yaml
consent_principles:
  - No source assessed without explicit opt-in
  - User sees exactly what is tracked
  - User can opt-out any source at any time
  - User can exclude specific activities from opted-in sources
```

### Evidence Sources

| Source | Signals | Skills Evidenced |
|--------|---------|------------------|
| **Code artifacts** | Structure, naming, error handling | Language proficiency, design patterns |
| **Debugging behavior** | Hypothesis forming, isolation | Problem decomposition, systematic thinking |
| **Questions asked** | Topics, depth, follow-ups | Metacognition, knowledge gaps |
| **Design artifacts** | Structure, trade-off analysis | Technical communication, systems thinking |

### Scale Levels

| Level | Scope | Assessment |
|-------|-------|------------|
| **Micro** | Line/statement | Automatic from code |
| **Meso** | Function/file | Patterns observed |
| **Macro** | Project/feature | Self-report + agent review |
| **Meta** | Portfolio/career | Accumulated evidence over time |

### Assisted Work Modifiers

```yaml
with_assistance: "Completed with help - reduced mastery update"
from_memory: "Completed without reference - full mastery update"
taught_then_applied: "Was shown, then used - partial update"
```

---

## Goals and Priority Modes

### Goal Structure

```yaml
goal:
  id: unique identifier
  statement: what the learner wants to achieve
  why: motivation/context
  competencies: list of skills that comprise this goal
  priority: elevated | background | maintenance
  mode: learning_primary | work_primary | blended
```

### Priority Modes

**work_primary**: Job tasks drive the day, learning is opportunistic
- Execute work tasks
- Surface overlaps with goals when they exist
- Stealth assessment from work artifacts
- Don't interrupt with learning pushes

**learning_primary**: Goal progress drives the day
- Prioritize goal competencies
- Suggest dedicated learning activities
- Explicit assessment acceptable
- Push harder toward gaps

**blended**: Specific goals elevated, others opportunistic
- Elevated goals get active push
- Other goals remain opportunistic
- Balance based on per-goal priority

### Push Mechanisms

- **Opportunity surfacing**: Work task overlaps with goal competency
- **Gap highlighting**: Low mastery skill not recently practiced
- **Stretch challenges**: Ready for harder application
- **Reflection prompts**: End of day/week review

---

## Context Management (The Balloons Origin)

The Journeyman project pioneered the context curation concepts that became Balloons:

### Context Graph

Everything in LLM working memory is a **node** with relationships:

```yaml
node_types:
  general:
    - input: User input
    - response: LLM response content
    - tool_call: Tool invocation
    - tool_result: Output from tool call
    - breadcrumb: Archived node summary
  learning:
    - probe: Assessment question
    - teach: Explanation/instruction
    - practice: Practice problem
    - feedback: Response to answer
    - evaluation: Assessment with BKT
```

### Retention Levels (Derived from Graph Traversal)

| Level | Behavior |
|-------|----------|
| **Pinned** | Always in context, never archived |
| **Held** | In context while reachable from pinned nodes |
| **Floating** | Not reachable, can be archived |

### Archival (Not Deletion)

Nothing is deleted. Archival means:
1. Flush full content to disk
2. Replace in-context with **breadcrumb** (ID + type + summary)
3. Can be **hydrated** (reloaded) later if needed

### User-Controlled Context

The user controls what LLM sees each turn:
- Select/deselect nodes for inclusion
- Pin/unpin to mark as permanent anchors
- Archive floating nodes (converts to breadcrumb)
- Accept/reject proposed hydrations

---

## Process Learnings from Live Cycles

*From actual tutoring sessions (January 2026)*

### What Worked

**Probe-based calibration**: One probe revealed specific mental model errors. Didn't need multiple questions to diagnose.

**Learner-driven practice**: Learners say "more practice" and "make it harder" unprompted. The "learner drives when enough" principle held.

**Prior knowledge detection**: When probe comes back correct immediately, cycle is fast - confirms existing skill rather than teaches new one.

**Variable cycle length**: Same structure, different duration based on prior knowledge.

**Visible reasoning**: "Your thinking is very informative and helpful for learning" - showing HOW to think is pedagogically valuable.

### Key Insights

**Self-assessment nuance:**
- Fails for: Faded knowledge (don't know what you don't know)
- Works for: Never learned (you know what you haven't been exposed to)

**Distinguishing failure modes** (can't tell from outside):
- Didn't understand
- Can't apply flexibly
- Reading/execution error

Solutions:
- Ask for reasoning BEFORE accepting answer
- Have learner restate question first
- Multiple reps - reading errors are random, model gaps are consistent

**Transfer tasks are non-negotiable**: Even when initial probe is correct, complete the cycle with transfer tasks. One correct answer could be lucky (P(guess) = 0.25).

---

## Architecture Insights

### Scattered State Problem

Multiple files with cross-references is fragile. LLM will leave disparate documents stale.

**Solution**: Clear separation of concerns:
- Context/curriculum (what to learn) - separate from knowledge nodes (how well learned)
- Flat HashMap keyed by full path for easy node updates
- LLM sees concatenated context, server updates nodes

### Branch Agent Isolation

Child branch details pollute parent context.

**Proposed solution**: Each branch spawns child agent, returns summary to parent. Parent continues with clean context.

This insight directly influenced Balloons' fork/merge model.

---

## Relationship to Balloons

Journeyman's experiments directly spawned Balloons:

| Journeyman Concept | Balloons Evolution |
|-------------------|-------------------|
| Context graph (pinned/held/floating) | COPY/COMPRESS/DROP per turn |
| Archival with breadcrumbs | ArchiveBlock with structured summary |
| Branch agent isolation | Fork/merge workflow |
| LLM sees raw state | Transparent context tree |
| User-controlled context | Per-turn context curation |
| Session as unit of work | Session with turns model |
| Goals with priority modes | Goal/Plan/Todo hierarchy |

---

## Future Integration Possibilities

### Learning Goals in Balloons

Extend the existing goal system:

```yaml
goal:
  type: "work" | "learning"
  # Learning goals add:
  mastery_target: 0.85
  current_confidence: 0.0-1.0
  bkt_params: {p_know, p_learn, p_guess, p_slip}
  evidence: [{session_id, result, timestamp}]
```

### Sessions as Evidence

Each session bound to a goal/plan/todo could track:
- What skills were exercised
- Mastery updates from the work
- Evidence of understanding

### Tutor Mode

A special session mode where Claude acts as tutor:
- Uses the learning cycle methodology
- Records mastery updates per turn
- Binds to a learning goal
- Thinks aloud deliberately

### Skill Overlay

Keep goals for work. Add parallel **Skill** entities for learning:
- Skills linked to goals ("to achieve goal X, need skills A, B, C")
- Sessions generate evidence for skills while achieving goals
- Priority engine incorporates learning needs

---

## Key Takeaways

1. **Knowledge is a graph**, not a list. Dependencies, prerequisites, and relationships matter.

2. **Transparency builds trust**. Showing the learner the same metrics you use creates shared understanding.

3. **Transfer is everything**. Same-example practice is memory, not understanding.

4. **Cycles complete, skills persist**. Sessions end; knowledge evolves across sessions.

5. **Context is precious**. Curating what the LLM sees enables focused, effective interaction.

6. **Branch, don't restart**. When prerequisites surface, handle them surgically and return.

7. **One probe is enough**. Well-chosen assessment is efficient assessment.

8. **Mastery, not time**. The exit condition is demonstrated capability, not hours spent.

---

*This document preserves concepts from the Journeyman project for future reference and potential integration into Balloons or similar systems.*
