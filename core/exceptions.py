"""Exceptions for Claude runner and related components."""


class RateLimitError(Exception):
    """Raised when Claude CLI reports hitting the rate limit."""
    pass


class InputRequiredError(Exception):
    """Raised when Claude CLI is waiting for user input (question asked)."""
    pass
