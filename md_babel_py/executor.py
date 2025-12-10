"""Execute code blocks."""

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from .config import Config, EvaluatorConfig, get_evaluator
from .parser import CodeBlock
from .session import SessionManager
from .types import ExecutionResult

logger = logging.getLogger(__name__)


def substitute_params(
    args: list[str],
    params: dict[str, str],
    input_file: str | None = None,
) -> list[str]:
    """Substitute {param} placeholders in arguments with values from params.

    Args:
        args: List of command arguments, may contain {param} placeholders.
        params: Dictionary of parameter values from code block.
        input_file: Path to input file (substitutes {input_file}).

    Returns:
        List of arguments with placeholders substituted.

    Special placeholders:
        {input_file}: Path to temp file containing code block content.

    Example:
        >>> substitute_params(["--mode", "{mode}"], {"mode": "GraphDAG"})
        ["--mode", "GraphDAG"]
    """
    result = []
    for arg in args:
        substituted = arg
        # Substitute custom params
        for key, value in params.items():
            substituted = substituted.replace(f"{{{key}}}", value)
        # Substitute special input_file placeholder
        if input_file:
            substituted = substituted.replace("{input_file}", input_file)
        result.append(substituted)
    return result


class Executor:
    """Execute code blocks, handling both isolated and session-based execution."""

    def __init__(self, config: Config):
        self.config = config
        self.session_manager = SessionManager()

    def execute(self, block: CodeBlock) -> ExecutionResult:
        """Execute a code block and return the result."""
        evaluator = get_evaluator(self.config, block.language)

        if evaluator is None:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=f"No evaluator configured for language: {block.language}",
            )

        if block.session and evaluator.session:
            return self._execute_session(block, evaluator)
        else:
            return self._execute_isolated(block, evaluator)

    def _execute_isolated(self, block: CodeBlock, evaluator: EvaluatorConfig) -> ExecutionResult:
        """Execute a code block in isolation (subprocess)."""
        input_file_path: str | None = None
        output_file_path: str | None = None
        temp_files: list[str] = []

        try:
            # Merge default params with block params (block params override defaults)
            params = {**evaluator.default_params, **block.params}

            # Check if evaluator expects {output} but block doesn't provide it
            args_str = " ".join(evaluator.default_arguments)
            uses_output = "{output}" in args_str or "{output}" in evaluator.prefix or "{output}" in evaluator.suffix
            if uses_output and "output" not in block.params:
                return ExecutionResult(
                    stdout="",
                    stderr="",
                    success=False,
                    error_message=f"Evaluator '{block.language}' requires output=<path> parameter",
                )

            # Apply prefix/suffix to code
            code = evaluator.prefix + block.code + evaluator.suffix

            # Substitute params in code (e.g., {output} placeholder)
            for key, value in params.items():
                code = code.replace(f"{{{key}}}", value)

            # Create temp input file if needed
            if evaluator.input_extension:
                fd, input_file_path = tempfile.mkstemp(suffix=evaluator.input_extension)
                temp_files.append(input_file_path)
                with os.fdopen(fd, 'w') as f:
                    f.write(code)
                logger.debug(f"Wrote code to temp file: {input_file_path}")

            # Get output file from params if specified
            if "output" in block.params:
                output_file_path = block.params["output"]
                # Ensure parent directory exists
                Path(output_file_path).parent.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Output file: {output_file_path}")

            # Substitute params in arguments
            args = substitute_params(
                evaluator.default_arguments,
                params,
                input_file=input_file_path,
            )
            cmd = [evaluator.path] + args
            logger.debug(f"Executing command: {cmd}")

            # Determine stdin
            stdin_input = None if evaluator.input_extension else code

            result = subprocess.run(
                cmd,
                input=stdin_input,
                capture_output=True,
                text=True,
                timeout=60,  # Longer timeout for tools like openscad
            )

            if result.returncode != 0:
                return ExecutionResult(
                    stdout=result.stdout,
                    stderr=result.stderr,
                    success=False,
                    error_message=f"Exit code: {result.returncode}",
                )

            # Read output from file or stdout
            if output_file_path and os.path.exists(output_file_path):
                # Return image reference for the output file
                stdout = f"![output]({output_file_path})"
            else:
                stdout = result.stdout

            return ExecutionResult(
                stdout=stdout,
                stderr=result.stderr,
                success=True,
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message="Execution timed out after 60 seconds",
            )
        except Exception as e:
            logger.exception("Execution failed")
            return ExecutionResult(
                stdout="",
                stderr="",
                success=False,
                error_message=str(e),
            )
        finally:
            # Clean up temp files (but not output images)
            for temp_path in temp_files:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _execute_session(self, block: CodeBlock, evaluator: EvaluatorConfig) -> ExecutionResult:
        """Execute a code block in a persistent session."""
        # This is only called when evaluator.session is not None (checked in execute())
        assert evaluator.session is not None
        session_key = (block.language, block.session)
        return self.session_manager.execute(
            session_key=session_key,
            code=block.code,
            language=block.language,
            session_config=evaluator.session,
        )

    def cleanup(self) -> None:
        """Clean up all sessions."""
        self.session_manager.cleanup()
