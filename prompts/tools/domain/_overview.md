## Domain Plugin Tools

You can dynamically load domain plugins to gain new capabilities. Domain plugins provide
specialized tools for specific tasks (like playing chess, managing databases, etc.).

### When to Use Domain Plugins

- **User asks for specialized capabilities**: "Let's play chess" → load chess domain
- **Task requires domain-specific tools**: Load the relevant domain before starting work
- **Cleaning up**: Unload domains you no longer need to reduce context usage

### Example Workflow

1. User says "Let's play chess"
2. Call `list_domains` to see what's available
3. Call `load_domain` with `domain_id: "chess"`
4. The chess tools (like `chess_new_game`, `chess_move`) become available
5. When done, call `unload_domain` to clean up

