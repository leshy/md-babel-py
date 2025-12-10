"""Session management for persistent REPL execution.

This module handles persistent REPL sessions for languages that support them.
Sessions allow variables and state to persist across multiple code blocks.
"""

import logging
import os
import select
import subprocess
import time
from dataclasses import dataclass
from typing import IO

from .config import SessionConfig
from .types import ExecutionResult

logger = logging.getLogger(__name__)

# Built-in marker commands per language
MARKERS: dict[str, str] = {
    "python": "print('__MD_BABEL_END__')",
    "python3": "print('__MD_BABEL_END__')",
    "node": "console.log('__MD_BABEL_END__')",
    "javascript": "console.log('__MD_BABEL_END__')",
    "ruby": "puts '__MD_BABEL_END__'",
    "sh": "echo '__MD_BABEL_END__'",
    "bash": "echo '__MD_BABEL_END__'",
    "zsh": "echo '__MD_BABEL_END__'",
    "fish": "echo '__MD_BABEL_END__'",
}

# Built-in REPL prompts per language (for output cleaning)
DEFAULT_PROMPTS: dict[str, list[str]] = {
    "python": [">>> ", "... "],
    "python3": [">>> ", "... "],
    "node": ["> ", "... "],
    "javascript": ["> ", "... "],
    "ruby": ["irb(main):", ">> "],
    "sh": ["$ "],
    "bash": ["$ "],
    "zsh": ["% "],
    "fish": ["> "],
}

END_MARKER = "__MD_BABEL_END__"


@dataclass
class Session:
    """A persistent REPL session.

    Attributes:
        process: The subprocess running the REPL.
        marker: The marker command used to detect end of output.
        prompts: List of prompt patterns to strip from output.
    """
    process: subprocess.Popen[str]
    marker: str
    prompts: list[str]


class SessionManager:
    """Manage persistent REPL sessions.

    Each session is identified by a (language, session_name) tuple.
    Sessions are created on first use and reused for subsequent executions.
    """

    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str | None], Session] = {}

    def get_marker(self, language: str, session_config: SessionConfig) -> str:
        """Get the marker command for a language.

        Args:
            language: The programming language.
            session_config: The session configuration.

        Returns:
            The marker command to use.
        """
        if session_config.marker:
            return session_config.marker
        return MARKERS.get(language, f"echo '{END_MARKER}'")

    def get_prompts(self, language: str, session_config: SessionConfig) -> list[str]:
        """Get the prompt patterns for a language.

        Args:
            language: The programming language.
            session_config: The session configuration.

        Returns:
            List of prompt patterns to strip from output.
        """
        if session_config.prompts:
            return session_config.prompts
        return DEFAULT_PROMPTS.get(language, [])

    def get_or_create_session(
        self,
        session_key: tuple[str, str | None],
        language: str,
        session_config: SessionConfig,
    ) -> Session:
        """Get existing session or create a new one.

        Args:
            session_key: Tuple of (language, session_name).
            language: The programming language.
            session_config: The session configuration.

        Returns:
            The session object.
        """
        if session_key in self.sessions:
            session = self.sessions[session_key]
            # Check if process is still alive
            if session.process.poll() is None:
                return session
            # Process died, remove it
            logger.debug(f"Session {session_key} died, creating new one")
            del self.sessions[session_key]

        logger.debug(f"Creating new session {session_key} with command: {session_config.command}")

        # Create new session
        process = subprocess.Popen(
            session_config.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,  # Unbuffered
        )

        marker = self.get_marker(language, session_config)
        prompts = self.get_prompts(language, session_config)
        session = Session(process=process, marker=marker, prompts=prompts)
        self.sessions[session_key] = session

        # Drain any startup output from the REPL
        self._drain_startup(session)

        return session

    def _drain_startup(self, session: Session, timeout: float = 0.5) -> None:
        """Drain startup messages from REPL.

        Args:
            session: The session to drain.
            timeout: How long to wait for output.
        """
        stdout = session.process.stdout
        if stdout is None:
            return

        while True:
            readable, _, _ = select.select([stdout], [], [], timeout)
            if not readable:
                break
            chunk = os.read(stdout.fileno(), 4096)
            if not chunk:
                break
            logger.debug(f"Drained startup output: {chunk!r}")

    def execute(
        self,
        session_key: tuple[str, str | None],
        code: str,
        language: str,
        session_config: SessionConfig,
    ) -> ExecutionResult:
        """Execute code in a session.

        Args:
            session_key: Tuple of (language, session_name).
            code: The code to execute.
            language: The programming language.
            session_config: The session configuration.

        Returns:
            The execution result.
        """
        try:
            session = self.get_or_create_session(session_key, language, session_config)
        except Exception as e:
            logger.exception("Failed to start session")
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=f"Failed to start session: {e}",
            )

        stdin = session.process.stdin
        if stdin is None:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message="Session stdin is not available",
            )

        # Send code followed by marker
        try:
            logger.debug(f"Sending code to session: {code[:100]}...")
            stdin.write(code + "\n")
            stdin.write(session.marker + "\n")
            stdin.flush()
        except BrokenPipeError:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message="Session process died unexpectedly",
            )

        # Read output until we see the marker
        stdout_parts: list[str] = []

        try:
            output = self._read_until_marker(session, timeout=30)
            stdout_parts.append(output)
        except TimeoutError:
            return ExecutionResult(
                stdout="".join(stdout_parts),
                stderr="",
                success=False,
                error_message="Execution timed out",
            )
        except Exception as e:
            logger.exception("Error reading session output")
            return ExecutionResult(
                stdout="".join(stdout_parts),
                stderr="",
                success=False,
                error_message=str(e),
            )

        # Clean up output
        stdout = "".join(stdout_parts)
        stdout = self._clean_output(stdout, session, code)

        return ExecutionResult(
            stdout=stdout,
            stderr="",
            success=True,
        )

    def _read_until_marker(self, session: Session, timeout: float) -> str:
        """Read stdout until the end marker appears.

        Args:
            session: The session to read from.
            timeout: Maximum time to wait in seconds.

        Returns:
            The output read from the session.

        Raises:
            TimeoutError: If the marker is not received within timeout.
        """
        output: list[str] = []
        start_time = time.time()
        stdout = session.process.stdout

        if stdout is None:
            return ""

        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError("Timed out waiting for marker")

            readable, _, _ = select.select([stdout], [], [], 0.1)
            if readable:
                chunk = os.read(stdout.fileno(), 4096)
                if chunk:
                    text = chunk.decode('utf-8', errors='replace')
                    output.append(text)
                    logger.debug(f"Read chunk: {text!r}")

                    # Check if we have the marker
                    full_output = "".join(output)
                    if END_MARKER in full_output:
                        return full_output

            # Check if process died
            if session.process.poll() is not None:
                # Process exited, get remaining output
                remaining = stdout.read()
                if remaining:
                    output.append(remaining)
                break

        return "".join(output)

    def _clean_output(self, output: str, session: Session, code: str) -> str:
        """Clean REPL noise from output.

        Args:
            output: The raw output from the REPL.
            session: The session (for prompt patterns).
            code: The code that was executed (to filter echoes).

        Returns:
            Cleaned output with prompts and markers removed.
        """
        lines = output.split('\n')
        cleaned: list[str] = []

        for line in lines:
            # Skip the marker output line
            if END_MARKER in line:
                continue

            # Check if line starts with a known prompt
            stripped = line.lstrip()
            prompt_found = False

            for prompt in session.prompts:
                if stripped.startswith(prompt):
                    # Extract content after prompt
                    content = stripped[len(prompt):]

                    # Skip if it's echoing our code or marker
                    if content.strip() and content.strip() not in code and 'MD_BABEL' not in content:
                        cleaned.append(content)
                    prompt_found = True
                    break

            if not prompt_found and 'MD_BABEL' not in line:
                # Keep non-prompt lines that don't contain our marker
                cleaned.append(line)

        # Remove trailing empty lines
        while cleaned and not cleaned[-1].strip():
            cleaned.pop()

        # Remove leading empty lines
        while cleaned and not cleaned[0].strip():
            cleaned.pop(0)

        return '\n'.join(cleaned)

    def cleanup(self) -> None:
        """Terminate all sessions."""
        for session_key, session in self.sessions.items():
            logger.debug(f"Cleaning up session {session_key}")
            try:
                session.process.terminate()
                session.process.wait(timeout=2)
            except Exception:
                try:
                    session.process.kill()
                except Exception:
                    pass
        self.sessions.clear()
