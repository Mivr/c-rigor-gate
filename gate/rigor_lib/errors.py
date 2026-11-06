"""The one error type that means "the gate itself could not decide" (exit code 2)."""


class InternalError(Exception):
    """Unreadable input, tool failure, or any state the gate cannot judge."""
