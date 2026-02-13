"""Token counting utilities.

Provides both synchronous (blocking) and asynchronous token counting.
Uses the Rust tiktoken-rs implementation via balloons_storage for performance.
Falls back to Python tiktoken if Rust module unavailable.
"""

from typing import Optional

# Try to use Rust tokenizer (much faster, releases GIL)
try:
    from balloons_storage import Tokenizer as RustTokenizer
    _rust_tokenizer: Optional[RustTokenizer] = RustTokenizer()
except ImportError:
    _rust_tokenizer = None

# Python fallback
import tiktoken
_python_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding.

    Uses Rust tiktoken-rs if available (faster, releases GIL).
    Falls back to Python tiktoken otherwise.
    """
    if _rust_tokenizer is not None:
        return _rust_tokenizer.count_tokens(text)
    return len(_python_encoder.encode(text))


def count_tokens_batch(texts: list[str]) -> list[int]:
    """Count tokens for multiple texts in batch.

    More efficient than calling count_tokens repeatedly when using Rust backend
    as it parallelizes across the thread pool.
    """
    if _rust_tokenizer is not None:
        return _rust_tokenizer.count_tokens_batch(texts)
    # Python fallback - sequential
    return [len(_python_encoder.encode(text)) for text in texts]


def count_messages_tokens(messages: list) -> int:
    """Count tokens for a list of Message objects."""
    total = 0
    for msg in messages:
        # Add role prefix tokens
        total += 2  # "User:" or "Assistant:" prefix
        total += count_tokens(msg.content)
        total += 2  # newlines between messages
    return total


def is_rust_backend() -> bool:
    """Check if the Rust tokenizer backend is available."""
    return _rust_tokenizer is not None
