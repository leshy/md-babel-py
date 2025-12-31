"""Integration tests for md-babel-py."""

import re
import subprocess
from pathlib import Path

TESTS_DIR = Path(__file__).parent


def normalize_output(text: str) -> str:
    """Normalize output for comparison by replacing variable paths."""
    # Replace temp file paths like /tmp/tmpXXXXXX.py with placeholder
    text = re.sub(r'/tmp/tmp[a-zA-Z0-9_]+\.py', '<tmpfile>', text)
    return text


def test_integration():
    """Run integration test and compare output."""
    input_file = TESTS_DIR / "integration.md"
    expected_file = TESTS_DIR / "integration.expected.md"

    result = subprocess.run(
        ["md-babel-py", "run", str(input_file), "--stdout"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Command failed: {result.stderr}"

    expected = normalize_output(expected_file.read_text())
    actual = normalize_output(result.stdout)

    # Normalize trailing newlines
    expected = expected.rstrip() + "\n"
    actual = actual.rstrip() + "\n"

    assert actual == expected, f"Output mismatch:\n--- Expected ---\n{expected}\n--- Actual ---\n{actual}"
