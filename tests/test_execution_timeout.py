"""Isolated execution timeout (CLI and MD_BABEL_EXECUTION_TIMEOUT)."""

import argparse
import os
import subprocess
from pathlib import Path
import tempfile

import pytest

from md_babel_py.cli import resolve_isolated_execution_timeout


def _run_md_babel(content: str, extra_args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(content)
        f.flush()
        name = f.name

    try:
        cmd = ["md-babel-py", "run", name, "--stdout", *extra_args]
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return subprocess.run(cmd, capture_output=True, text=True, env=merged, timeout=120)
    finally:
        Path(name).unlink(missing_ok=True)


def test_resolve_cli_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MD_BABEL_EXECUTION_TIMEOUT", "99")
    args = argparse.Namespace(execution_timeout=12.0)
    assert resolve_isolated_execution_timeout(args) == 12.0


def test_resolve_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MD_BABEL_EXECUTION_TIMEOUT", "45")
    args = argparse.Namespace(execution_timeout=None)
    assert resolve_isolated_execution_timeout(args) == 45.0


def test_resolve_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MD_BABEL_EXECUTION_TIMEOUT", raising=False)
    args = argparse.Namespace(execution_timeout=None)
    assert resolve_isolated_execution_timeout(args) == 60.0


def test_execution_timeout_flag_kills_slow_block() -> None:
    content = """```python
import time
time.sleep(30)
```
"""
    result = _run_md_babel(content, ["--execution-timeout", "1"])
    assert result.returncode == 1
    assert "timed out" in result.stderr.lower()
    assert "1" in result.stderr or "after" in result.stderr.lower()


def test_execution_timeout_env_kills_slow_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MD_BABEL_EXECUTION_TIMEOUT", raising=False)
    content = """```python
import time
time.sleep(30)
```
"""
    result = _run_md_babel(content, [], env={"MD_BABEL_EXECUTION_TIMEOUT": "1"})
    assert result.returncode == 1
    assert "timed out" in result.stderr.lower()
