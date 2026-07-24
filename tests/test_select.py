"""Tests for -k block selection and the run summary."""

import os
import subprocess
from pathlib import Path

import pytest

from md_babel_py.cli import block_matches, format_summary
from md_babel_py.parser import find_code_blocks


DOC = '''```python session=alpha
print("from alpha")
```

```sh
echo "from shell"
```

```python session=beta output=beta.txt
print("from beta")
```
'''


def blocks():
    return find_code_blocks(DOC)


def run(md_file: Path, extra: list[str], tmp_path: Path):
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    cmd = ["python", "-m", "md_babel_py.cli", "run", str(md_file), "--stdout"] + extra
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_matches_code_content():
    """-k searches the code itself."""
    matched = [b for b in blocks() if block_matches(b, "from shell")]
    assert [b.language for b in matched] == ["sh"]


def test_matches_language():
    """-k searches the language tag."""
    matched = [b for b in blocks() if block_matches(b, "python")]
    assert len(matched) == 2


def test_matches_session_name():
    """-k searches the session name."""
    matched = [b for b in blocks() if block_matches(b, "beta")]
    assert all(b.session == "beta" for b in matched)
    assert len(matched) == 1


def test_matches_session_written_as_in_the_fence():
    """-k session=alpha works, matching how the block is actually tagged."""
    matched = [b for b in blocks() if block_matches(b, "session=alpha")]
    assert [b.session for b in matched] == ["alpha"]


def test_matches_params_as_key_value():
    """-k searches params rendered as key=value."""
    matched = [b for b in blocks() if block_matches(b, "output=beta.txt")]
    assert len(matched) == 1


def test_match_is_case_insensitive():
    """-k ignores case."""
    assert [b for b in blocks() if block_matches(b, "FROM ALPHA")]


def test_no_match_selects_nothing():
    """A needle that appears nowhere selects no blocks."""
    assert [b for b in blocks() if block_matches(b, "nonexistent")] == []


@pytest.mark.parametrize(
    "success,total,cached,expected",
    [
        (3, 3, 0, "3/3 blocks executed successfully."),
        (3, 3, 3, "3/3 blocks executed successfully (3 from cache)."),
        (3, 3, 1, "3/3 blocks executed successfully (1 from cache, 2 executed)."),
        (0, 0, 0, "0/0 blocks executed successfully."),
        # Cache hits can include blocks that produce no result; never over-report.
        (2, 2, 5, "2/2 blocks executed successfully (2 from cache)."),
    ],
)
def test_format_summary(success, total, cached, expected):
    assert format_summary(success, total, cached) == expected


def test_k_runs_only_matching_blocks(tmp_path):
    """End to end: -k restricts execution to matching blocks."""
    md_file = tmp_path / "doc.md"
    md_file.write_text(DOC)

    result = run(md_file, ["-k", "from shell"], tmp_path)

    assert result.returncode == 0
    assert "from shell" in result.stdout
    assert "[1/1] Executing sh" in result.stderr
    # The python blocks were not run, so no results were written for them.
    assert "from alpha" not in result.stdout.split("```sh")[-1]


def test_k_reports_when_nothing_matches(tmp_path):
    """-k with no matches says so and exits cleanly."""
    md_file = tmp_path / "doc.md"
    md_file.write_text(DOC)

    result = run(md_file, ["-k", "nothing-here"], tmp_path)

    assert result.returncode == 0
    assert "No blocks match" in result.stderr


def test_summary_reports_cached_blocks(tmp_path):
    """The Done line says how many blocks came from cache."""
    md_file = tmp_path / "doc.md"
    md_file.write_text('```python\nprint("hello")\n```\n')

    first = run(md_file, [], tmp_path)
    assert "1/1 blocks executed successfully." in first.stderr

    second = run(md_file, [], tmp_path)
    assert "1/1 blocks executed successfully (1 from cache)." in second.stderr
