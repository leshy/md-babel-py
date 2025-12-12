"""Integration tests for caching behavior."""

import subprocess
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    """Use a temporary cache directory."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path / "md-babel" / "v1"


@pytest.fixture
def simple_md(tmp_path):
    """Create a simple markdown file for testing."""
    md_file = tmp_path / "test.md"
    md_file.write_text('''```python
print("cached output")
```
''')
    return md_file


def run_md_babel(file_path: Path, extra_args: list[str] = None, env: dict = None):
    """Run md-babel-py and return result."""
    import os
    cmd = ["python", "-m", "md_babel_py.cli", "run", str(file_path), "--stdout"]
    if extra_args:
        cmd.extend(extra_args)

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    return subprocess.run(cmd, capture_output=True, text=True, env=run_env)


class TestCacheIntegration:
    """Integration tests for cache behavior."""

    def test_cache_miss_then_hit(self, simple_md, temp_cache):
        """First run should miss, second should hit."""
        import os
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        # First run - cache miss
        result1 = run_md_babel(simple_md, env=env)
        assert result1.returncode == 0
        assert "cached output" in result1.stdout
        assert "0 hits, 1 misses" in result1.stderr

        # Second run - cache hit
        result2 = run_md_babel(simple_md, env=env)
        assert result2.returncode == 0
        assert "cached output" in result2.stdout
        assert "1 hits, 0 misses" in result2.stderr

    def test_no_cache_flag_bypasses_cache(self, simple_md, temp_cache):
        """--no-cache should always execute."""
        import os
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        # First run to populate cache
        result1 = run_md_babel(simple_md, env=env)
        assert result1.returncode == 0

        # Run with --no-cache
        result2 = run_md_babel(simple_md, extra_args=["--no-cache"], env=env)
        assert result2.returncode == 0
        assert "cached output" in result2.stdout
        # Should not report cache stats when disabled
        assert "hits" not in result2.stderr

    def test_code_change_invalidates_cache(self, tmp_path, temp_cache):
        """Changing code should cause cache miss."""
        import os
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        md_file = tmp_path / "test.md"

        # First version
        md_file.write_text('''```python
print("version 1")
```
''')
        result1 = run_md_babel(md_file, env=env)
        assert "version 1" in result1.stdout
        assert "0 hits, 1 misses" in result1.stderr

        # Same code - should hit
        result2 = run_md_babel(md_file, env=env)
        assert "1 hits, 0 misses" in result2.stderr

        # Change code - should miss
        md_file.write_text('''```python
print("version 2")
```
''')
        result3 = run_md_babel(md_file, env=env)
        assert "version 2" in result3.stdout
        assert "0 hits, 1 misses" in result3.stderr

    def test_session_blocks_not_cached(self, tmp_path, temp_cache):
        """Session blocks should not be cached."""
        import os
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        md_file = tmp_path / "test.md"
        md_file.write_text('''```python session=main
x = 42
print(x)
```
''')

        # First run
        result1 = run_md_babel(md_file, env=env)
        assert result1.returncode == 0
        assert "42" in result1.stdout

        # Second run - should NOT hit cache (sessions aren't cached)
        result2 = run_md_babel(md_file, env=env)
        assert result2.returncode == 0
        # No cache stats because session blocks bypass cache entirely
        assert "hits" not in result2.stderr or "0 hits" in result2.stderr

    def test_cache_stores_output_files(self, tmp_path, temp_cache):
        """Cache should store and restore output files."""
        import os
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        output_dir = tmp_path / "output"
        output_dir.mkdir()
        output_file = output_dir / "result.txt"

        md_file = tmp_path / "test.md"
        md_file.write_text(f'''```sh
echo "file content" > {output_file}
cat {output_file}
```
''')

        # First run - creates output file
        result1 = run_md_babel(md_file, env=env)
        assert result1.returncode == 0
        assert output_file.exists()

        # Delete output file
        output_file.unlink()
        assert not output_file.exists()

        # Second run - should hit cache, output recreated from stdout
        result2 = run_md_babel(md_file, env=env)
        assert result2.returncode == 0
        assert "1 hits" in result2.stderr
