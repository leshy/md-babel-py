"""Test exit codes for md-babel-py."""

import subprocess
from pathlib import Path
import tempfile

TESTS_DIR = Path(__file__).parent


def run_md_babel(content: str, extra_args: list[str] = None) -> subprocess.CompletedProcess:
    """Run md-babel-py on content and return result."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        f.flush()

        cmd = ["md-babel-py", "run", f.name, "--stdout"]
        if extra_args:
            cmd.extend(extra_args)

        result = subprocess.run(cmd, capture_output=True, text=True)
        Path(f.name).unlink()
        return result


def test_success_exit_code():
    """Normal successful execution returns 0."""
    content = """
```python
print("hello")
```
"""
    result = run_md_babel(content)
    assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"


def test_error_exit_code():
    """Unexpected error returns non-zero."""
    content = """
```python
raise ValueError("boom")
```
"""
    result = run_md_babel(content)
    assert result.returncode == 1, f"Expected 1, got {result.returncode}: {result.stderr}"


def test_expected_error_success():
    """expected-error block that fails returns 0."""
    content = """
```python expected-error
raise ValueError("this should fail")
```
"""
    result = run_md_babel(content)
    assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"


def test_expected_error_failure():
    """expected-error block that succeeds returns non-zero."""
    content = """
```python expected-error
print("this should have failed but didn't")
```
"""
    result = run_md_babel(content)
    assert result.returncode == 1, f"Expected 1, got {result.returncode}: {result.stderr}"
    assert "expected error but block succeeded" in result.stderr


def test_skip_does_not_execute():
    """skip block is not executed."""
    content = """
```python skip
raise ValueError("this would fail if executed")
```
"""
    result = run_md_babel(content)
    assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"


def test_no_result_still_executes():
    """no-result block executes but doesn't add result."""
    content = """
```python session=test no-result
x = 42
```

```python session=test
print(x)
```
"""
    result = run_md_babel(content)
    assert result.returncode == 0, f"Expected 0, got {result.returncode}: {result.stderr}"
    assert "42" in result.stdout
    # Should only have one Result block (from second block)
    assert result.stdout.count("<!--Result:-->") == 1


def test_unconfigured_language_warning():
    """Unconfigured language shows warning but doesn't fail."""
    content = """
```unknownlang
some code
```
"""
    result = run_md_babel(content)
    assert result.returncode == 0
    assert "No evaluators configured for: unknownlang" in result.stderr


def test_multiple_errors_stops_at_first():
    """Execution stops at first unexpected error."""
    content = """
```python
print("aaa")
```

```python
raise ValueError("second fails")
```

```python
print("zzz")
```
"""
    result = run_md_babel(content)
    assert result.returncode == 1
    # First block ran
    assert result.stdout.count("<!--Result:-->") == 1
    # Second block failed
    assert result.stdout.count("<!--Error:-->") == 1
    # Third block never ran (only 2 blocks executed out of 3)
    assert "2/3" in result.stderr or "1/2" in result.stderr  # Progress shows we stopped early
