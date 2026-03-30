# Context Management Features

Balloons provides granular control over conversation context through a turn-level selection system. Each message turn can be assigned one of three context modes: **COPY** (include verbatim), **COMPRESS** (LLM-summarized before use), or **DROP** (exclude from context).

Context management is integrated with session history, derivation, and fork/merge workflows:
- supported clients expose controls for reviewing prior turns and adjusting their context modes
- context-building logic reconstructs conversation history, including tool uses and results, according to those modes
- token counting and context inspection help users understand what will be sent to the model
- forked or derived sessions can selectively inherit curated context from earlier work
- merge metadata preserves summaries of work completed in child conversations

The current supported product surface is the headless server plus web UI. Older TUI-specific widgets and keybindings are removed and unsupported.

---

**TL;DR:** Hierarchical chat sessions let you branch conversations at any point, giving you fine-grained control over which context flows into each fork—ideal for exploring ideas at different levels of detail without polluting unrelated threads.
