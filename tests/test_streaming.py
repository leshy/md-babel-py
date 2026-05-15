"""Tests for live stdout/stderr streaming of code-block output."""

import subprocess
import tempfile
from pathlib import Path


def run_md_babel(content: str, extra_args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run md-babel-py against a temp markdown file with --stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        f.flush()

        cmd = ["md-babel-py", "run", f.name, "--stdout", "--no-cache"]
        if extra_args:
            cmd.extend(extra_args)

        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        finally:
            Path(f.name).unlink(missing_ok=True)


def test_isolated_python_streams_stdout_to_stderr():
    """Block stdout is mirrored to the CLI's stderr while executing."""
    content = '```python\nprint("STREAM_MARKER_42")\n```\n'
    result = run_md_babel(content)
    assert result.returncode == 0, result.stderr
    # The captured output is also re-inserted into markdown on real stdout.
    assert "STREAM_MARKER_42" in result.stdout
    # And it is streamed live to stderr so the user sees it.
    assert "STREAM_MARKER_42" in result.stderr


def test_isolated_python_streams_stderr_to_stderr():
    """Block stderr also flows to the CLI's stderr."""
    content = '```python\nimport sys\nsys.stderr.write("ERR_MARKER_X\\n")\n```\n'
    result = run_md_babel(content)
    assert result.returncode == 0, result.stderr
    assert "ERR_MARKER_X" in result.stderr


def test_quiet_suppresses_streaming():
    """--quiet stops live streaming but still captures into markdown."""
    content = '```python\nprint("QUIET_MARKER_99")\n```\n'
    result = run_md_babel(content, extra_args=["--quiet"])
    assert result.returncode == 0, result.stderr
    # Still inserted into the markdown output on stdout.
    assert "QUIET_MARKER_99" in result.stdout
    # But NOT echoed live on stderr.
    assert "QUIET_MARKER_99" not in result.stderr


def test_stdout_channel_not_contaminated():
    """Live block output goes to stderr, not to real stdout (which carries markdown).

    The printed marker is constructed at runtime so it doesn't appear in the
    source; that way any occurrence on stdout must come from the rewritten
    result block (legitimate) — and any extra occurrence would indicate a leak.
    """
    content = (
        '```python\n'
        'print("CHANNEL" + "_LEAK_PROBE")\n'
        '```\n'
    )
    result = run_md_babel(content)
    assert result.returncode == 0, result.stderr
    # Exactly once on stdout: inside the rewritten ```results block.
    assert result.stdout.count("CHANNEL_LEAK_PROBE") == 1
    # And should appear at least once on stderr (the live stream).
    assert "CHANNEL_LEAK_PROBE" in result.stderr


def test_python_session_streams_live():
    """Python session blocks (JSON protocol) also stream live."""
    content = (
        '```python session=main\n'
        'print("SESSION_LIVE_X")\n'
        '```\n'
    )
    result = run_md_babel(content)
    assert result.returncode == 0, result.stderr
    assert "SESSION_LIVE_X" in result.stdout  # captured into markdown
    assert "SESSION_LIVE_X" in result.stderr  # streamed live


def test_marker_session_streams_live():
    """Non-Python sessions (marker protocol, e.g. sh) also stream live."""
    content = (
        '```sh session=s1\n'
        'echo MARKER_SH_LIVE\n'
        '```\n'
    )
    result = run_md_babel(content)
    assert result.returncode == 0, result.stderr
    assert "MARKER_SH_LIVE" in result.stdout  # captured
    assert "MARKER_SH_LIVE" in result.stderr  # live
