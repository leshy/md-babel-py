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

# Pattern for new-style result/error blocks: ```results ... ``` or ```error ... ```
RESULT_PATTERN_FENCED = re.compile(
    r'^```(results|error)[^\n]*\n(.*?)^```[ \t]*$',
    re.MULTILINE | re.DOTALL
)

# Legacy pattern: <!--Result:--> / <!--Error:--> + plain fence (read-only, for migration)
RESULT_PATTERN_FENCED_LEGACY = re.compile(
    r'^<!--(Result|Error):-->\n```[^\n]*\n(.*?)^```[ \t]*$',
    re.MULTILINE | re.DOTALL
)

# Pattern for bare image result line (with optional legacy <!--Result:--> marker above)
RESULT_PATTERN_IMAGE = re.compile(
    r'^(?:<!--Result:-->\n)?(!\[[^\]]*\]\([^)]+\))[ \t]*$',
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
        if language in ("results", "error"):
            continue  # These are output markers, not executable code

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
    """Find all result/error blocks in markdown content.

    Recognizes both new-style ```results / ```error fences and legacy
    <!--Result:-->/<!--Error:--> + fence/image forms.
    """
    blocks = []

    # New-style fenced result blocks: ```results / ```error
    for match in RESULT_PATTERN_FENCED.finditer(content):
        lang = match.group(1)
        result_content = match.group(2)
        kind = "Result" if lang == "results" else "Error"

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

    # Legacy fenced result blocks: <!--Result:--> / <!--Error:--> + ``` fence
    for match in RESULT_PATTERN_FENCED_LEGACY.finditer(content):
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

    return blocks


_IMAGE_LINE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)[ \t]*$')

# `output=none` means "md-babel does not manage an output file here", so images
# under such a block are the author's and are never touched.
_NO_OUTPUT = 'none'


def _is_result_opening(stripped: str) -> bool:
    """Check if a line opens a result fence (new ``` or legacy comment)."""
    if stripped in ('<!--Result:-->', '<!--Error:-->'):
        return True
    if stripped.startswith('```'):
        info = stripped[3:].strip()
        first_tok = info.split()[0] if info else ''
        return first_tok in ('results', 'error')
    return False


def find_block_result_range(content: str, block: CodeBlock) -> tuple[int, int] | None:
    """Find the range of any existing result/error block following a code block.

    Returns (start_line, end_line) of the result block(s), or None if no result exists.
    Handles:
      - New-style ```results / ```error fences
      - Legacy <!--Result:--> / <!--Error:--> markers (with following fence or image)
      - Bare image results (only when the image path matches the block's `output=`
        param exactly, so user-authored prose images and `output=none` markers
        don't get clobbered)
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

    result_start: int | None = None
    result_end: int | None = None
    output_path = block.params.get("output", "")

    while line_idx < len(lines):
        line = lines[line_idx]
        stripped = line.strip()
        marker_start_idx = line_idx  # 0-indexed line where this result starts
        consumed_end: int | None = None

        if stripped.startswith('```'):
            # New-style fence: ```results / ```error
            info = stripped[3:].strip()
            first_tok = info.split()[0] if info else ''
            if first_tok in ('results', 'error'):
                for i in range(line_idx + 1, len(lines)):
                    if lines[i].strip() == '```':
                        consumed_end = i + 1  # 1-indexed, inclusive
                        line_idx = i + 1
                        break
                else:
                    break  # No closing fence
            else:
                break

        elif stripped in ('<!--Result:-->', '<!--Error:-->'):
            # Legacy marker: followed by fence or image
            if line_idx + 1 >= len(lines):
                break
            next_line = lines[line_idx + 1]
            if next_line.startswith('```'):
                for i in range(line_idx + 2, len(lines)):
                    if lines[i].strip() == '```':
                        consumed_end = i + 1
                        line_idx = i + 1
                        break
                else:
                    break
            elif next_line.startswith('!['):
                consumed_end = line_idx + 2
                line_idx += 2
            else:
                break

        elif (
            output_path
            and output_path != _NO_OUTPUT
            and (m := _IMAGE_LINE_RE.match(line))
            and m.group(2) == output_path
        ):
            # Bare image result (new format), and only the one md-babel is about to
            # rewrite: its path still matches this block's `output=`. Any other
            # image is the author's -- hand-written links, and everything under an
            # `output=none` block -- and is never removed, even when the block's
            # own result block above it is replaced.
            consumed_end = line_idx + 1  # 1-indexed, inclusive
            line_idx += 1

        else:
            break

        if consumed_end is None:
            break

        if result_start is None:
            # Include preceding blank line if present
            if first_blank_idx is not None:
                result_start = first_blank_idx + 1  # Convert to 1-indexed
            else:
                result_start = marker_start_idx + 1  # Convert to 1-indexed
        result_end = consumed_end

        # After consuming, look for an adjacent error block
        while line_idx < len(lines) and not lines[line_idx].strip():
            line_idx += 1
        if line_idx >= len(lines):
            break
        if not _is_result_opening(lines[line_idx].strip()):
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
