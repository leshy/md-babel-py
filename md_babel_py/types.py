"""Shared types for md-babel-py."""

from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Result of executing a code block.

    Attributes:
        stdout: Standard output from the execution.
        stderr: Standard error from the execution.
        success: Whether the execution completed successfully.
        error_message: Human-readable error message if execution failed.
    """
    stdout: str
    stderr: str
    success: bool
    error_message: str | None = None
