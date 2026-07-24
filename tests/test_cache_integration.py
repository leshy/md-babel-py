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

    def test_unchanged_session_is_served_from_cache(self, tmp_path, temp_cache):
        """An unchanged session replays from cache instead of re-executing."""
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        md_file = tmp_path / "test.md"
        md_file.write_text('''```python session=main
x = 42
print(x)
```

```python session=main
print(x + 1)
```
''')

        result1 = run_md_babel(md_file, env=env)
        assert result1.returncode == 0
        assert "42" in result1.stdout
        assert "43" in result1.stdout
        assert "0 hits, 2 misses" in result1.stderr

        result2 = run_md_babel(md_file, env=env)
        assert result2.returncode == 0
        assert "42" in result2.stdout
        assert "43" in result2.stdout
        assert "2 hits, 0 misses" in result2.stderr

    def test_editing_a_session_block_invalidates_it(self, tmp_path, temp_cache):
        """Editing a session block re-runs the session; results stay correct."""
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        md_file = tmp_path / "test.md"
        md_file.write_text('''```python session=main
x = 42
```

```python session=main
print(x)
```
''')

        assert "42" in run_md_babel(md_file, env=env).stdout

        # Change the first block: the second depends on it and must not be
        # served the stale "42" from the previous run.
        md_file.write_text('''```python session=main
x = 99
```

```python session=main
print(x)
```
''')

        result = run_md_babel(md_file, env=env)
        assert result.returncode == 0
        assert "99" in result.stdout
        assert "42" not in result.stdout

    def test_no_cache_flag_reruns_session(self, tmp_path, temp_cache):
        """--no-cache forces session execution even when everything is cached."""
        env = {"XDG_CACHE_HOME": str(temp_cache.parent.parent)}

        md_file = tmp_path / "test.md"
        md_file.write_text('''```python session=main
print("session output")
```
''')

        run_md_babel(md_file, env=env)
        result = run_md_babel(md_file, extra_args=["--no-cache"], env=env)
        assert result.returncode == 0
        assert "session output" in result.stdout
        assert "hits" not in result.stderr

    def test_dropping_output_param_shows_the_printed_result(self, tmp_path, temp_cache):
        """A block that stops writing a file shows its printed output.

        The cached image-link result must not be served for a block that no longer
        has `output=`. The image line itself stays: removing links is the author's
        call, never md-babel's.
        """
        import os
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(temp_cache.parent.parent)

        def run_in_place() -> None:
            # The shared helper forces --stdout; this bug is about the rewrite.
            subprocess.run(
                ["python", "-m", "md_babel_py.cli", "run", str(md_file)],
                capture_output=True, text=True, env=env, check=False,
            )

        md_file = tmp_path / "test.md"
        svg = tmp_path / "out.svg"
        md_file.write_text(f'''```python output={svg.name}
print("IGNORED WHILE WRITING A FILE")
open(r"{svg}", "w").write("<svg/>")
```
''')

        run_in_place()
        assert f"![output]({svg.name})" in md_file.read_text()

        # Same code, but no longer writing a file.
        md_file.write_text(f'''```python
print("PRINTED OUTPUT")
```

![output]({svg.name})
''')

        run_in_place()

        after = md_file.read_text()
        assert "PRINTED OUTPUT" in after.split("```results")[-1]
        assert f"![output]({svg.name})" in after, f"image link was removed:\n{after}"

    def test_output_none_never_touches_image_links(self, tmp_path, temp_cache):
        """output=none: replace the generated result block, never the author's links."""
        import os
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(temp_cache.parent.parent)

        md_file = tmp_path / "test.md"
        links = (
            "![output](assets/one.svg)\n"
            "\n"
            "![output](assets/two.png)\n"
        )
        md_file.write_text(
            '```python output=none\nprint("FIRST")\n```\n\n'
            "```results\nFIRST\n```\n\n" + links
        )

        # Change the printed value: the result block must update, links must not move.
        md_file.write_text(
            '```python output=none\nprint("SECOND")\n```\n\n'
            "```results\nFIRST\n```\n\n" + links
        )
        subprocess.run(
            ["python", "-m", "md_babel_py.cli", "run", str(md_file)],
            capture_output=True, text=True, env=env, check=False,
        )

        after = md_file.read_text()
        assert "SECOND" in after.split("```results")[1]
        assert "FIRST" not in after, "stale result block was not replaced"
        assert after.count("![output](assets/one.svg)") == 1
        assert after.count("![output](assets/two.png)") == 1

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
