- testing PLAN. methodology
	- review tests -  critical review of EACH test methodically
- [done] docs PLAN - review docs, still valid? (bulk cleanup done; keep pruning as plans complete)
- [done] openai runner to use contextbuilder (shared select_turns + render_* in core.context; gemini runner removed)
- system memory?
- judge
- remove ssl? issue with websocket security
- session naming query option? like on first message? tool?
- now that we have traffic capture, do an audit of messages for different session types
- mermaid/plantuml rendering?
- queued/steering messages seem to disappear - should linger in the UI as it gets applied
- stt feature was better before we last modified it 

## bigger features
- scheduling/watching
	- cron-job stuff

## ui stuff
- static panes limit flexibility
- layout is just not great
- latest message highlighting
- minimap has gaps
- browser eventually gets perf/hiccups from mem growth

## Ported from deleted plans (still-open items)

Streaming / runners (from the incremental-streaming plan, after the async-generator fix):
- `_format_block(ThinkingBlock)` returns `None`, so reasoning is dropped from history entirely. Before enabling any reasoning-replay feature, confirm an exchange containing an assistant-turn-that-produces-no-text doesn't create an empty assistant entry or break strict alternation (`validate_generation_boundary`).
- Reasoning replay into context should be a per-backend opt-in (llama.cpp/Qwen3 benefits; Anthropic requires signed blocks returned verbatim; OpenAI wants structured reasoning items), not a global toggle.
- Embedded tool-call false positives: ordinary prose containing ``` ` ```json {"name":` or `Read(file=...)` ``` is flagged as a malformed tool call and dumped (seen in runner.log / tool_call_debug.log).

Subscriptions (from the subscription-layers refactor; phases 1/2/4/5 shipped):
- Deferred: split `turnFinished` into `turnCompleted` (HEADER, metadata only) + `turnBody` (BODY, full content). Optional optimization; today full turnFinished goes to both HEADER and BODY subscribers.
- Deferred: subscription downgrade when switching sessions (drop DELTA layer on blur instead of resubscribing).

Session review / model evaluation (superseded drafts deleted; the shipped review modal covers the core):
- A "judge" role / rubric-based longitudinal scoring was specced but never built; revisit only if the review modal proves insufficient for model comparison.