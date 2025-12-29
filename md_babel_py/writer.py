"""Write execution results back to markdown."""

import re
from dataclasses import dataclass

from .parser import CodeBlock, find_block_result_range
from .types import ExecutionResult

# ANSI escape sequence pattern (covers SGR codes, cursor movement, etc.)
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return ANSI_ESCAPE_PATTERN.sub('', text)


@dataclass
class BlockResult:
    """A code block paired with its execution result."""
    block: CodeBlock
    result: ExecutionResult


def apply_results(content: str, results: list[BlockResult]) -> str:
    """Apply execution results to markdown content.

    Processes blocks in reverse order to avoid line number shifts.
    """
    lines = content.split('\n')

    # Sort by start_line descending to process from bottom to top
    sorted_results = sorted(results, key=lambda r: r.block.start_line, reverse=True)

    for block_result in sorted_results:
        block = block_result.block
        result = block_result.result

        # Check if ANSI stripping is requested (ansi=false)
        ansi_param = block.params.get("ansi", "true").lower()
        if ansi_param == "false":
            result = ExecutionResult(
                stdout=strip_ansi(result.stdout),
                stderr=strip_ansi(result.stderr),
                success=result.success,
                error_message=result.error_message,
            )

        # Find existing result block range and remove it first
        existing_range = find_block_result_range(content, block)

        if existing_range:
            # Remove existing result block
            start_idx = existing_range[0] - 1  # Convert to 0-indexed
            end_idx = existing_range[1]  # Already 1-indexed, use as exclusive end
            lines = lines[:start_idx] + lines[end_idx:]
            content = '\n'.join(lines)

        # Build new result block(s)
        new_result_lines = build_result_block(result)

        # Insert after code block (or after </details> if present)
        insert_idx = block.end_line  # 0-indexed position after block

        # Check if </details> follows the code block (within next few lines)
        for i in range(insert_idx, min(insert_idx + 5, len(lines))):
            if lines[i].strip() == '</details>':
                insert_idx = i + 1
                break

        # Only add blank line if there isn't one already
        needs_blank = insert_idx == 0 or lines[insert_idx - 1].strip() != ''
        prefix = [''] if needs_blank else []
        lines = lines[:insert_idx] + prefix + new_result_lines + lines[insert_idx:]

        # Update content for next iteration's range finding
        content = '\n'.join(lines)

    return '\n'.join(lines)


def build_result_block(result: ExecutionResult) -> list[str]:
    """Build the result/error block lines.

    Only includes stderr/error block if the execution failed (success=False).
    Successful executions only show stdout.
    Image outputs (starting with ![) are not wrapped in code blocks.
    """
    blocks: list[str] = []

    # Add stdout as Result block
    stdout = result.stdout.strip()
    if stdout:
        # Check if output is an image reference (don't wrap in code block)
        if stdout.startswith('!['):
            blocks.extend([
                '<!--Result:-->',
                stdout,
            ])
        else:
            blocks.extend([
                '<!--Result:-->',
                '```',
                result.stdout.rstrip(),
                '```',
            ])

    # Only add stderr/error block if execution failed
    if not result.success:
        error_content = result.stderr.strip()
        if result.error_message:
            if error_content:
                error_content += '\n\n' + result.error_message
            else:
                error_content = result.error_message

        if error_content:
            blocks.extend([
                '<!--Error:-->',
                '```',
                error_content,
                '```',
            ])

    return blocks
