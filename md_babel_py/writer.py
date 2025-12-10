"""Write execution results back to markdown."""

from dataclasses import dataclass

from .parser import CodeBlock, find_block_result_range
from .types import ExecutionResult


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

        # Find existing result block range
        existing_range = find_block_result_range(content, block)

        # Build new result block(s)
        new_result_lines = build_result_block(result)

        if existing_range:
            # Replace existing result block
            start_idx = existing_range[0] - 1  # Convert to 0-indexed
            end_idx = existing_range[1]  # Already 1-indexed, use as exclusive end
            lines = lines[:start_idx] + new_result_lines + lines[end_idx:]
        else:
            # Insert after code block
            insert_idx = block.end_line  # 0-indexed position after block
            lines = lines[:insert_idx] + [''] + new_result_lines + lines[insert_idx:]

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
