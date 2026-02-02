# System Prompt Samples

This directory contains example system prompts you can use with Balloons.

## Usage

1. Copy a prompt file to `~/.balloons/prompts/` (or any location you prefer)
2. Customize the prompt for your needs
3. Reference it in your `~/.balloons/config.yaml`:

```yaml
backends:
  openrouter:
    type: openai
    base_url: https://openrouter.ai/api/v1
    api_key: ${OPENROUTER_API_KEY}
    model: anthropic/claude-sonnet-4
    system_prompt: ~/.balloons/prompts/coding-assistant.md
```

## Available Samples

- **coding-assistant.md** - Full-featured coding assistant with guidelines for writing clean code
- **minimal.md** - Bare minimum prompt for simple tasks or models with limited context

## Tips

- For Claude backends (`type: claude`), there's already a ~19.3k token built-in system prompt. Your custom prompt adds additional context.
- For OpenAI-compatible backends, you typically need to provide a system prompt - the model has no default instructions.
- Keep prompts concise for smaller models or when context window is limited
- The status bar shows context token usage including your system prompt
