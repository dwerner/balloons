"""Exceptions for Claude runner and related components."""


class RateLimitError(Exception):
    """Raised when Claude CLI reports hitting the rate limit."""
    pass


class InputRequiredError(Exception):
    """Raised when Claude CLI is waiting for user input (question asked)."""
    pass


class BackendNotFoundError(Exception):
    """Raised when a session references a backend that doesn't exist in config."""

    def __init__(self, backend_name: str, available_backends: list[str]):
        self.backend_name = backend_name
        self.available_backends = available_backends
        super().__init__(
            f"Backend '{backend_name}' not found. Available: {', '.join(available_backends)}"
        )
