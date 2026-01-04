"""Session management for persistent REPL execution.

This module handles persistent REPL sessions for languages that support them.
Sessions allow variables and state to persist across multiple code blocks.

Two protocols are supported:
- "json": Structured JSON I/O (recommended for Python via session_server.py)
- "marker": Traditional REPL with end markers (for other languages)
"""

import json
import logging
import os
import select
import subprocess
import time
from dataclasses import dataclass

from .config import SessionConfig
from .types import ExecutionResult

logger = logging.getLogger(__name__)

# Built-in marker commands per language (for marker protocol)
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

# Built-in REPL prompts per language (for output cleaning in marker protocol)
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


def prepare_code_for_repl(code: str, language: str) -> str:
    """Prepare code for REPL execution by adding blank lines after indented blocks.

    Python's interactive REPL requires a blank line after indented blocks
    (if/for/with/def/class/etc.) to signal the block is complete.

    Only needed for marker protocol; JSON protocol handles this properly.
    """
    if language not in ("python", "python3"):
        return code

    lines = code.split('\n')
    result = []
    prev_indented = False

    for line in lines:
        stripped = line.rstrip()
        is_indented = bool(stripped) and (line.startswith(' ') or line.startswith('\t'))
        is_base_level = bool(stripped) and not is_indented

        if prev_indented and is_base_level:
            result.append('')

        result.append(line)
        prev_indented = is_indented

    return '\n'.join(result)


@dataclass
class Session:
    """A persistent session."""
    process: subprocess.Popen[str]
    protocol: str  # "json" or "marker"
    marker: str  # Only used for marker protocol
    prompts: list[str]  # Only used for marker protocol


class SessionManager:
    """Manage persistent sessions.

    Each session is identified by a (language, session_name) tuple.
    Sessions are created on first use and reused for subsequent executions.
    """

    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str | None], Session] = {}

    def get_or_create_session(
        self,
        session_key: tuple[str, str | None],
        language: str,
        session_config: SessionConfig,
    ) -> Session:
        """Get existing session or create a new one."""
        if session_key in self.sessions:
            session = self.sessions[session_key]
            if session.process.poll() is None:
                return session
            logger.debug(f"Session {session_key} died, creating new one")
            del self.sessions[session_key]

        logger.debug(f"Creating new session {session_key} with command: {session_config.command}")

        process = subprocess.Popen(
            session_config.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered for JSON protocol
        )

        # Get marker/prompts for marker protocol
        marker = session_config.marker or MARKERS.get(language, f"echo '{END_MARKER}'")
        prompts = session_config.prompts or DEFAULT_PROMPTS.get(language, [])

        session = Session(
            process=process,
            protocol=session_config.protocol,
            marker=marker,
            prompts=prompts,
        )
        self.sessions[session_key] = session

        # For marker protocol, drain startup output
        if session_config.protocol == "marker":
            self._drain_startup(session)

        return session

    def _drain_startup(self, session: Session, timeout: float = 0.5) -> None:
        """Drain startup messages from REPL (marker protocol only)."""
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
        """Execute code in a session."""
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

        if session.protocol == "json":
            return self._execute_json(session, code)
        else:
            return self._execute_marker(session, code, language)

    def _execute_json(self, session: Session, code: str) -> ExecutionResult:
        """Execute code using JSON protocol."""
        stdin = session.process.stdin
        stdout = session.process.stdout

        if stdin is None or stdout is None:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message="Session I/O not available",
            )

        # Send JSON request
        request = json.dumps({"code": code})
        try:
            logger.debug(f"Sending JSON request: {request[:100]}...")
            stdin.write(request + "\n")
            stdin.flush()
        except BrokenPipeError:
            # Capture stderr to show why the process died
            stderr_output = ""
            if session.process.stderr:
                stderr_output = session.process.stderr.read()
            error_msg = "Session process died unexpectedly"
            if stderr_output:
                error_msg += f":\n{stderr_output}"
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=error_msg,
            )

        # Read JSON response (with timeout)
        try:
            # Use select for timeout
            start_time = time.time()
            timeout = 30.0

            while True:
                if time.time() - start_time > timeout:
                    return ExecutionResult(
                        stdout="",
                        stderr="",
                        success=False,
                        error_message="Execution timed out",
                    )

                readable, _, _ = select.select([stdout], [], [], 0.1)
                if readable:
                    line = stdout.readline()
                    if line:
                        logger.debug(f"Received JSON response: {line[:100]}...")
                        break

                if session.process.poll() is not None:
                    # Capture stderr to show why the process died
                    stderr_output = ""
                    if session.process.stderr:
                        stderr_output = session.process.stderr.read()
                    error_msg = "Session process exited unexpectedly"
                    if stderr_output:
                        error_msg += f":\n{stderr_output}"
                    return ExecutionResult(
                        stdout="",
                        stderr="",
                        success=False,
                        error_message=error_msg,
                    )

            response = json.loads(line)
            err = response.get("err", "")
            return ExecutionResult(
                stdout=response.get("out", ""),
                stderr="",  # Don't duplicate - use error_message for errors
                success=response.get("ok", False),
                error_message=err if not response.get("ok") and err else None,
            )

        except json.JSONDecodeError as e:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=f"Invalid JSON response: {e}",
            )
        except Exception as e:
            logger.exception("Error reading session response")
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=str(e),
            )

    def _execute_marker(self, session: Session, code: str, language: str) -> ExecutionResult:
        """Execute code using marker protocol (traditional REPL)."""
        stdin = session.process.stdin
        if stdin is None:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message="Session stdin is not available",
            )

        # Prepare code for REPL (add blank lines after indented blocks)
        code = prepare_code_for_repl(code, language)

        # Send code followed by marker
        try:
            logger.debug(f"Sending code to session: {code[:100]}...")
            stdin.write(code + "\n")
            stdin.write(session.marker + "\n")
            stdin.flush()
        except BrokenPipeError:
            # Capture stderr to show why the process died
            stderr_output = ""
            if session.process.stderr:
                stderr_output = session.process.stderr.read()
            error_msg = "Session process died unexpectedly"
            if stderr_output:
                error_msg += f":\n{stderr_output}"
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=error_msg,
            )

        # Read output until we see the marker
        try:
            output = self._read_until_marker(session, timeout=30)
        except TimeoutError:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message="Execution timed out",
            )
        except Exception as e:
            logger.exception("Error reading session output")
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=str(e),
            )

        # Clean up output
        stdout = self._clean_output(output, session, code)

        return ExecutionResult(
            stdout=stdout,
            stderr="",
            success=True,
        )

    def _read_until_marker(self, session: Session, timeout: float) -> str:
        """Read stdout until the end marker appears (marker protocol)."""
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

                    full_output = "".join(output)
                    if END_MARKER in full_output:
                        return full_output

            if session.process.poll() is not None:
                remaining = stdout.read()
                if remaining:
                    output.append(remaining)
                break

        return "".join(output)

    def _clean_output(self, output: str, session: Session, code: str) -> str:
        """Clean REPL noise from output (marker protocol)."""
        lines = output.split('\n')
        cleaned: list[str] = []

        for line in lines:
            if END_MARKER in line:
                continue

            stripped = line.lstrip()
            prompt_found = False

            for prompt in session.prompts:
                if stripped.startswith(prompt):
                    content = stripped[len(prompt):]
                    if content.strip() and content.strip() not in code and 'MD_BABEL' not in content:
                        cleaned.append(content)
                    prompt_found = True
                    break

            if not prompt_found and 'MD_BABEL' not in line:
                cleaned.append(line)

        while cleaned and not cleaned[-1].strip():
            cleaned.pop()
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
