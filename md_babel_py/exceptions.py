"""Custom exceptions for md-babel-py."""


class MdBabelError(Exception):
    """Base exception for md-babel-py errors."""
    pass


class ConfigError(MdBabelError):
    """Configuration-related errors.

    Raised when:
    - Config file is not valid JSON
    - Required fields are missing
    - Field values are invalid types
    """
    pass


class ExecutionError(MdBabelError):
    """Code execution errors.

    Raised when:
    - Evaluator command fails to start
    - Execution times out
    - Process returns non-zero exit code
    """
    pass


class SessionError(MdBabelError):
    """Session management errors.

    Raised when:
    - Session process fails to start
    - Session process dies unexpectedly
    - Marker not received within timeout
    """
    pass
