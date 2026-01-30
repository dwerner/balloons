"""Token counting utilities using tiktoken."""

import tiktoken

# Claude uses a similar tokenizer to cl100k_base
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using tiktoken (cl100k_base approximation for Claude)."""
    return len(_encoder.encode(text))


def count_messages_tokens(messages: list) -> int:
    """Count tokens for a list of Message objects."""
    total = 0
    for msg in messages:
        # Add role prefix tokens
        total += 2  # "User:" or "Assistant:" prefix
        total += count_tokens(msg.content)
        total += 2  # newlines between messages
    return total
