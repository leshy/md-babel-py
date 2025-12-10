"""Integration tests for md-babel-py."""

import subprocess
from pathlib import Path

TESTS_DIR = Path(__file__).parent


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

    expected = expected_file.read_text()
    actual = result.stdout

    # Normalize trailing newlines
    expected = expected.rstrip() + "\n"
    actual = actual.rstrip() + "\n"

    assert actual == expected, f"Output mismatch:\n--- Expected ---\n{expected}\n--- Actual ---\n{actual}"
