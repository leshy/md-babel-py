"""Write execution results back to markdown."""

import re
from dataclasses import dataclass

from .parser import CodeBlock, find_block_result_range, extract_result_content
from .types import ExecutionResult

# ANSI escape sequence pattern (covers SGR codes, cursor movement, etc.)
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

# Python memory address pattern (e.g., 0x7f3e6d151340)
MEMORY_ADDRESS_PATTERN = re.compile(r'0x[0-9a-fA-F]+')


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return ANSI_ESCAPE_PATTERN.sub('', text)


def normalize_output(text: str) -> str:
    """Normalize output for comparison by replacing volatile patterns.

    Replaces memory addresses so that outputs differing only in addresses
    are considered equal.
    """
    return MEMORY_ADDRESS_PATTERN.sub('0x...', text)


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

        # Build new result block(s)
        new_result_lines = build_result_block(result)

        # Find existing result block range
        existing_range = find_block_result_range(content, block)

        if existing_range:
            # Compare existing vs new output (normalized to ignore memory addresses)
            existing_content = extract_result_content(content, block)
            new_content = '\n'.join(new_result_lines)

            if normalize_output(existing_content or '') == normalize_output(new_content):
                # No meaningful change - skip this block
                continue

            # Remove existing result block
            start_idx = existing_range[0] - 1  # Convert to 0-indexed
            end_idx = existing_range[1]  # Already 1-indexed, use as exclusive end
            lines = lines[:start_idx] + lines[end_idx:]
            content = '\n'.join(lines)

        # Handle fold wrapping
        if block.fold is not None:
            lines, content = apply_fold_wrapper(lines, block)

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


def apply_fold_wrapper(lines: list[str], block: CodeBlock) -> tuple[list[str], str]:
    """Wrap a code block in <details> tags if not already wrapped.

    Returns updated lines and content.
    """
    start_idx = block.start_line - 1  # 0-indexed
    end_idx = block.end_line  # 0-indexed position after block

    # Check if already wrapped (look for <details> before the block)
    already_wrapped = False
    for i in range(start_idx - 1, max(start_idx - 3, -1), -1):
        line = lines[i].strip()
        if line.startswith('<details'):
            already_wrapped = True
            break
        elif line and not line.startswith('<!--'):
            # Non-empty, non-comment line means not wrapped
            break

    if already_wrapped:
        return lines, '\n'.join(lines)

    # Build summary text
    if block.fold:
        summary = block.fold
    else:
        summary = block.language.capitalize()

    # Insert <details><summary> before code block and </details> after
    details_open = [f'<details><summary>{summary}</summary>', '']
    details_close = ['', '</details>']

    lines = (
        lines[:start_idx] +
        details_open +
        lines[start_idx:end_idx] +
        details_close +
        lines[end_idx:]
    )

    # Update block line numbers to account for inserted lines
    # The block moved down by len(details_open) lines
    block.start_line += len(details_open)
    block.end_line += len(details_open)

    return lines, '\n'.join(lines)


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
