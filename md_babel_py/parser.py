"""Markdown parser to find fenced code blocks."""

import re
from dataclasses import dataclass


@dataclass
class CodeBlock:
    """A fenced code block in a markdown document."""
    language: str
    code: str
    session: str | None  # None means isolated execution
    expected_error: bool  # If True, expect this block to fail
    skip: bool  # If True, don't evaluate this block
    no_result: bool  # If True, evaluate but don't insert result
    fold: str | None  # None = no fold, "" = fold with default, str = custom summary
    start_line: int  # 1-indexed, line of opening fence
    end_line: int  # 1-indexed, line of closing fence
    info_string: str  # Full info string after opening fence
    params: dict[str, str]  # Custom parameters (key=value pairs from info string)


@dataclass
class ResultBlock:
    """An existing result block (<!--Result:--> or <!--Error:-->)."""
    kind: str  # "Result" or "Error"
    content: str
    start_line: int
    end_line: int


# Regex to match fenced code blocks
# Captures: opening fence (backticks/tildes), info string, code content
FENCE_PATTERN = re.compile(
    r'^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<info>[^\n]*)\n'
    r'(?P<code>.*?)'
    r'^(?P=indent)(?P=fence)[ \t]*$',
    re.MULTILINE | re.DOTALL
)

# Pattern for result/error blocks (with code fence)
RESULT_PATTERN_FENCED = re.compile(
    r'^<!--(Result|Error):-->\n```[^\n]*\n(.*?)^```[ \t]*$',
    re.MULTILINE | re.DOTALL
)

# Pattern for result blocks with image output (no code fence)
RESULT_PATTERN_IMAGE = re.compile(
    r'^<!--(Result):-->\n(!\[[^\]]*\]\([^)]+\))[ \t]*$',
    re.MULTILINE
)


def parse_info_string(info: str) -> tuple[str, dict[str, str], set[str]]:
    """Parse info string into language, metadata dict, and flags set.

    Example: "python session=main expected-error" -> ("python", {"session": "main"}, {"expected-error"})
    Example: 'python fold="Show Code"' -> ("python", {"fold": "Show Code"}, set())
    """
    info = info.strip()
    if not info:
        return "", {}, set()

    # Tokenize respecting quoted strings
    parts = tokenize_info_string(info)
    if not parts:
        return "", {}, set()

    language = parts[0]
    metadata = {}
    flags = set()

    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            # Remove surrounding quotes if present
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            metadata[key] = value
        else:
            flags.add(part)

    return language, metadata, flags


def tokenize_info_string(info: str) -> list[str]:
    """Tokenize info string, respecting quoted values.

    Example: 'python fold="Show Code" skip' -> ['python', 'fold="Show Code"', 'skip']
    """
    tokens = []
    current = []
    in_quotes = False
    quote_char = None

    for char in info:
        if char in ('"', "'") and not in_quotes:
            in_quotes = True
            quote_char = char
            current.append(char)
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
            current.append(char)
        elif char.isspace() and not in_quotes:
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(char)

    if current:
        tokens.append(''.join(current))

    return tokens


def find_code_blocks(content: str) -> list[CodeBlock]:
    """Find all fenced code blocks in markdown content."""
    blocks = []

    for match in FENCE_PATTERN.finditer(content):
        info_string = match.group('info')
        code = match.group('code')

        language, metadata, flags = parse_info_string(info_string)
        if not language:
            continue  # Skip blocks without language

        # Calculate line numbers (1-indexed)
        start_pos = match.start()
        end_pos = match.end()
        start_line = content[:start_pos].count('\n') + 1
        end_line = content[:end_pos].count('\n') + 1

        # Separate reserved metadata from custom params
        reserved_keys = {"session", "fold"}
        params = {k: v for k, v in metadata.items() if k not in reserved_keys}

        # Handle fold: can be flag (fold) or key=value (fold=Summary)
        fold: str | None = None
        if "fold" in flags:
            fold = ""  # Empty string means use default summary
        elif "fold" in metadata:
            fold = metadata["fold"]

        blocks.append(CodeBlock(
            language=language,
            code=code.rstrip('\n'),
            session=metadata.get("session"),
            expected_error="expected-error" in flags,
            skip="skip" in flags,
            no_result="no-result" in flags,
            fold=fold,
            start_line=start_line,
            end_line=end_line,
            info_string=info_string.strip(),
            params=params,
        ))

    return blocks


def find_result_blocks(content: str) -> list[ResultBlock]:
    """Find all result/error blocks in markdown content."""
    blocks = []

    # Find fenced result blocks
    for match in RESULT_PATTERN_FENCED.finditer(content):
        kind = match.group(1)
        result_content = match.group(2)

        start_pos = match.start()
        end_pos = match.end()
        start_line = content[:start_pos].count('\n') + 1
        end_line = content[:end_pos].count('\n') + 1

        blocks.append(ResultBlock(
            kind=kind,
            content=result_content.rstrip('\n'),
            start_line=start_line,
            end_line=end_line,
        ))

    # Find image result blocks (no code fence)
    for match in RESULT_PATTERN_IMAGE.finditer(content):
        kind = match.group(1)
        result_content = match.group(2)

        start_pos = match.start()
        end_pos = match.end()
        start_line = content[:start_pos].count('\n') + 1
        end_line = content[:end_pos].count('\n') + 1

        blocks.append(ResultBlock(
            kind=kind,
            content=result_content,
            start_line=start_line,
            end_line=end_line,
        ))

    return blocks


def find_block_result_range(content: str, block: CodeBlock) -> tuple[int, int] | None:
    """Find the range of any existing result/error block following a code block.

    Returns (start_line, end_line) of the result block(s), or None if no result exists.
    Handles both fenced code blocks and image results.
    """
    lines = content.split('\n')
    line_idx = block.end_line  # 0-indexed position after the block
    first_blank_idx = None  # Track first blank line before result (after </details>)

    # Skip blank lines and </details> tag
    while line_idx < len(lines) and (
        not lines[line_idx].strip() or lines[line_idx].strip() == '</details>'
    ):
        if lines[line_idx].strip() == '</details>':
            # Reset blank tracking after </details> - we don't want to remove it
            first_blank_idx = None
        elif first_blank_idx is None and not lines[line_idx].strip():
            first_blank_idx = line_idx
        line_idx += 1

    if line_idx >= len(lines):
        return None

    # Check for result/error comment
    result_start = None
    result_end = None

    while line_idx < len(lines):
        line = lines[line_idx]

        if line.strip() in ('<!--Result:-->', '<!--Error:-->'):
            if result_start is None:
                # Include preceding blank line if present
                if first_blank_idx is not None:
                    result_start = first_blank_idx + 1  # Convert to 1-indexed
                else:
                    result_start = line_idx + 1  # Convert to 1-indexed

            # Check what follows the comment
            if line_idx + 1 < len(lines):
                next_line = lines[line_idx + 1]

                if next_line.startswith('```'):
                    # Fenced code block - find closing fence
                    fence_line = line_idx + 1
                    for i in range(fence_line + 1, len(lines)):
                        if lines[i].strip() == '```':
                            result_end = i + 1  # 1-indexed, inclusive
                            line_idx = i + 1
                            break
                    else:
                        # No closing fence found
                        break
                elif next_line.startswith('!['):
                    # Image result - just this line
                    result_end = line_idx + 2  # 1-indexed (comment + image line)
                    line_idx = line_idx + 2
                else:
                    break
            else:
                break

            # Check for another result/error block
            while line_idx < len(lines) and not lines[line_idx].strip():
                line_idx += 1

            if line_idx >= len(lines):
                break

            if lines[line_idx].strip() not in ('<!--Result:-->', '<!--Error:-->'):
                break
        else:
            break

    if result_start and result_end:
        return (result_start, result_end)
    return None


def extract_result_content(content: str, block: CodeBlock) -> str | None:
    """Extract the text content of an existing result block.

    Returns the raw content (stdout/stderr text), or None if no result exists.
    """
    result_range = find_block_result_range(content, block)
    if not result_range:
        return None

    lines = content.split('\n')
    start_idx = result_range[0] - 1  # Convert to 0-indexed
    end_idx = result_range[1]  # 1-indexed, exclusive

    result_lines = lines[start_idx:end_idx]
    return '\n'.join(result_lines)
