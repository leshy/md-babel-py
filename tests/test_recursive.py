"""Test recursive directory processing for md-babel-py."""

import subprocess
from pathlib import Path
import tempfile


def run_md_babel(args: list[str]) -> subprocess.CompletedProcess:
    """Run md-babel-py with given arguments."""
    cmd = ["md-babel-py", "run"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def test_recursive_finds_nested_files():
    """--recursive finds .md files in subdirectories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create nested structure
        (root / "subdir").mkdir()
        (root / "subdir" / "deep").mkdir()

        # Create markdown files at various levels
        (root / "root.md").write_text("""
```python
print("root")
```
""")
        (root / "subdir" / "sub.md").write_text("""
```python
print("sub")
```
""")
        (root / "subdir" / "deep" / "deep.md").write_text("""
```python
print("deep")
```
""")

        result = run_md_babel([str(root), "--recursive", "--dry-run"])

        assert result.returncode == 0
        assert "root.md" in result.stderr
        assert "sub.md" in result.stderr
        assert "deep.md" in result.stderr


def test_recursive_processes_all_files():
    """--recursive actually executes blocks in all files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "subdir").mkdir()

        (root / "a.md").write_text("""
```python
print("AAA")
```
""")
        (root / "subdir" / "b.md").write_text("""
```python
print("BBB")
```
""")

        result = run_md_babel([str(root), "--recursive"])

        assert result.returncode == 0

        # Check files were modified
        a_content = (root / "a.md").read_text()
        b_content = (root / "subdir" / "b.md").read_text()

        assert "AAA" in a_content
        assert "<!--Result:-->" in a_content
        assert "BBB" in b_content
        assert "<!--Result:-->" in b_content


def test_directory_without_recursive_only_top_level():
    """Directory without --recursive only processes top-level .md files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "subdir").mkdir()

        (root / "top.md").write_text("""
```python
print("top")
```
""")
        (root / "subdir" / "nested.md").write_text("""
```python
print("nested")
```
""")

        result = run_md_babel([str(root)])

        assert result.returncode == 0

        # Top-level file should be processed
        top_content = (root / "top.md").read_text()
        assert "<!--Result:-->" in top_content

        # Nested file should NOT be processed
        nested_content = (root / "subdir" / "nested.md").read_text()
        assert "<!--Result:-->" not in nested_content


def test_recursive_stdout_not_supported():
    """--stdout is not supported with multiple files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "a.md").write_text("```python\nprint(1)\n```")
        (root / "b.md").write_text("```python\nprint(2)\n```")

        result = run_md_babel([str(root), "--recursive", "--stdout"])

        assert result.returncode == 1
        assert "--stdout not supported with multiple files" in result.stderr


def test_recursive_output_not_supported():
    """--output is not supported with multiple files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "a.md").write_text("```python\nprint(1)\n```")
        (root / "b.md").write_text("```python\nprint(2)\n```")

        result = run_md_babel([str(root), "--recursive", "-o", "out.md"])

        assert result.returncode == 1
        assert "--output not supported with multiple files" in result.stderr


def test_recursive_summary_shows_totals():
    """Recursive mode shows summary of all files processed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "a.md").write_text("```python\nprint(1)\n```")
        (root / "b.md").write_text("```python\nprint(2)\n```\n```python\nprint(3)\n```")

        result = run_md_babel([str(root), "--recursive"])

        assert result.returncode == 0
        # Should show total files and blocks
        assert "2 files" in result.stderr
        assert "3/3" in result.stderr or "3 blocks" in result.stderr.lower()


def test_recursive_failure_in_one_file():
    """Failure in one file still processes others but returns error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "a_good.md").write_text("```python\nprint('ok')\n```")
        (root / "b_bad.md").write_text("```python\nraise ValueError('boom')\n```")

        result = run_md_babel([str(root), "--recursive"])

        # Should return error due to failure
        assert result.returncode == 1

        # But good file should still have been processed
        a_content = (root / "a_good.md").read_text()
        assert "ok" in a_content


def test_single_file_still_works():
    """Single file argument still works as before."""
    with tempfile.TemporaryDirectory() as tmpdir:
        md_file = Path(tmpdir) / "test.md"
        md_file.write_text("```python\nprint('hello')\n```")

        result = run_md_babel([str(md_file)])

        assert result.returncode == 0
        content = md_file.read_text()
        assert "hello" in content


def test_empty_directory():
    """Empty directory returns success."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = run_md_babel([tmpdir, "--recursive"])

        assert result.returncode == 0
        assert "No markdown files found" in result.stderr


def test_recursive_ignores_non_md():
    """Recursive mode ignores non-.md files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        (root / "readme.txt").write_text("```python\nprint('txt')\n```")
        (root / "doc.md").write_text("```python\nprint('md')\n```")

        result = run_md_babel([str(root), "--recursive"])

        assert result.returncode == 0

        # .md file processed
        assert "md" in (root / "doc.md").read_text()
        assert "<!--Result:-->" in (root / "doc.md").read_text()

        # .txt file untouched (no Result added)
        assert "<!--Result:-->" not in (root / "readme.txt").read_text()
