"""Tests for the caching system."""

import json
import tempfile
from pathlib import Path

import pytest

from md_babel_py.cache import Cache, compute_cache_key, get_cache_dir
from md_babel_py.config import EvaluatorConfig
from md_babel_py.parser import CodeBlock
from md_babel_py.types import ExecutionResult


@pytest.fixture
def temp_cache_dir(tmp_path, monkeypatch):
    """Use a temporary directory for the cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return tmp_path / "md-babel" / "v1"


@pytest.fixture
def cache(temp_cache_dir):
    """Create a cache instance using temp directory."""
    return Cache(enabled=True)


@pytest.fixture
def sample_block():
    """Create a sample code block for testing."""
    return CodeBlock(
        language="python",
        code="print('hello')",
        session=None,
        expected_error=False,
        skip=False,
        no_result=False,
        fold=None,
        start_line=1,
        end_line=3,
        info_string="python",
        params={},
    )


@pytest.fixture
def sample_evaluator():
    """Create a sample evaluator config for testing."""
    return EvaluatorConfig(
        path="python3",
        default_arguments=["-c", "{code}"],
        session=None,
        input_extension=None,
        default_params={},
        prefix="",
        suffix="",
    )


@pytest.fixture
def sample_result():
    """Create a sample execution result for testing."""
    return ExecutionResult(
        stdout="hello\n",
        stderr="",
        success=True,
        error_message=None,
    )


class TestComputeCacheKey:
    """Tests for cache key computation."""

    def test_same_input_same_key(self, sample_block, sample_evaluator):
        """Same block and evaluator should produce same key."""
        key1 = compute_cache_key(sample_block, sample_evaluator)
        key2 = compute_cache_key(sample_block, sample_evaluator)
        assert key1 == key2

    def test_different_code_different_key(self, sample_block, sample_evaluator):
        """Different code should produce different key."""
        key1 = compute_cache_key(sample_block, sample_evaluator)

        block2 = CodeBlock(
            language="python",
            code="print('world')",  # Different code
            session=None,
            expected_error=False,
            skip=False,
            no_result=False,
            fold=None,
            start_line=1,
            end_line=3,
            info_string="python",
            params={},
        )
        key2 = compute_cache_key(block2, sample_evaluator)
        assert key1 != key2

    def test_different_evaluator_different_key(self, sample_block, sample_evaluator):
        """Different evaluator config should produce different key."""
        key1 = compute_cache_key(sample_block, sample_evaluator)

        eval2 = EvaluatorConfig(
            path="python3.11",  # Different path
            default_arguments=["-c", "{code}"],
            session=None,
            input_extension=None,
            default_params={},
            prefix="",
            suffix="",
        )
        key2 = compute_cache_key(sample_block, eval2)
        assert key1 != key2

    def test_output_param_ignored(self, sample_block, sample_evaluator):
        """Output param should not affect cache key."""
        key1 = compute_cache_key(sample_block, sample_evaluator)

        block2 = CodeBlock(
            language="python",
            code="print('hello')",
            session=None,
            expected_error=False,
            skip=False,
            no_result=False,
            fold=None,
            start_line=1,
            end_line=3,
            info_string="python output=foo.txt",
            params={"output": "foo.txt"},  # Has output param
        )
        key2 = compute_cache_key(block2, sample_evaluator)
        assert key1 == key2

    def test_other_params_affect_key(self, sample_block, sample_evaluator):
        """Non-output params should affect cache key."""
        key1 = compute_cache_key(sample_block, sample_evaluator)

        block2 = CodeBlock(
            language="python",
            code="print('hello')",
            session=None,
            expected_error=False,
            skip=False,
            no_result=False,
            fold=None,
            start_line=1,
            end_line=3,
            info_string="python format=json",
            params={"format": "json"},  # Has non-output param
        )
        key2 = compute_cache_key(block2, sample_evaluator)
        assert key1 != key2

    def test_key_length(self, sample_block, sample_evaluator):
        """Key should be 16 hex characters."""
        key = compute_cache_key(sample_block, sample_evaluator)
        assert len(key) == 16
        assert all(c in "0123456789abcdef" for c in key)


class TestCache:
    """Tests for the Cache class."""

    def test_disabled_cache_returns_none(self, temp_cache_dir):
        """Disabled cache should always return None."""
        cache = Cache(enabled=False)
        cache.put("test_key", ExecutionResult("out", "", True))
        assert cache.get("test_key") is None

    def test_miss_returns_none(self, cache):
        """Cache miss should return None."""
        assert cache.get("nonexistent") is None

    def test_put_and_get(self, cache, sample_result):
        """Should store and retrieve results."""
        cache.put("test_key", sample_result)
        result = cache.get("test_key")

        assert result is not None
        assert result.stdout == sample_result.stdout
        assert result.stderr == sample_result.stderr
        assert result.success == sample_result.success
        assert result.error_message == sample_result.error_message

    def test_get_creates_directory(self, temp_cache_dir):
        """Get should not fail if directory doesn't exist."""
        cache = Cache(enabled=True)
        assert cache.get("test") is None  # Should not raise

    def test_put_creates_directory(self, temp_cache_dir, sample_result):
        """Put should create cache directory if needed."""
        cache = Cache(enabled=True)
        cache.put("test_key", sample_result)
        assert temp_cache_dir.exists()

    def test_stats_tracking(self, cache, sample_result):
        """Should track hits and misses."""
        assert cache.stats == {"hits": 0, "misses": 0}

        cache.get("miss1")
        assert cache.stats == {"hits": 0, "misses": 1}

        cache.put("hit_key", sample_result)
        cache.get("hit_key")
        assert cache.stats == {"hits": 1, "misses": 1}

        cache.get("miss2")
        assert cache.stats == {"hits": 1, "misses": 2}

    def test_clear(self, cache, sample_result):
        """Should clear all cached entries."""
        cache.put("key1", sample_result)
        cache.put("key2", sample_result)

        count = cache.clear()
        assert count == 2
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_clear_empty_cache(self, cache):
        """Clear on empty cache should return 0."""
        assert cache.clear() == 0


class TestCacheWithOutputFiles:
    """Tests for caching blocks that produce output files."""

    def test_cache_output_file(self, cache, tmp_path):
        """Should cache output file content."""
        output_file = tmp_path / "output.txt"
        output_file.write_text("file content")

        result = ExecutionResult(
            stdout=f"![output]({output_file})",
            stderr="",
            success=True,
        )

        cache.put("out_key", result, output_file=str(output_file))

        # Delete original file
        output_file.unlink()
        assert not output_file.exists()

        # Should restore from cache
        cached = cache.get("out_key", output_file=str(output_file))
        assert cached is not None
        assert output_file.exists()
        assert output_file.read_text() == "file content"

    def test_cache_output_binary_file(self, cache, tmp_path):
        """Should cache binary output files."""
        output_file = tmp_path / "output.bin"
        binary_content = bytes(range(256))
        output_file.write_bytes(binary_content)

        result = ExecutionResult(
            stdout=f"![output]({output_file})",
            stderr="",
            success=True,
        )

        cache.put("bin_key", result, output_file=str(output_file))

        output_file.unlink()
        cache.get("bin_key", output_file=str(output_file))

        assert output_file.read_bytes() == binary_content

    def test_cache_creates_output_parent_dirs(self, cache, tmp_path):
        """Should create parent directories for output file."""
        output_file = tmp_path / "subdir" / "nested" / "output.txt"
        original = tmp_path / "original.txt"
        original.write_text("content")

        result = ExecutionResult(stdout="", stderr="", success=True)
        cache.put("nested_key", result, output_file=str(original))

        # Get with different output path
        cache.get("nested_key", output_file=str(output_file))
        assert output_file.exists()


class TestGetCacheDir:
    """Tests for cache directory resolution."""

    def test_uses_xdg_cache_home(self, monkeypatch, tmp_path):
        """Should use XDG_CACHE_HOME if set."""
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert get_cache_dir() == tmp_path / "md-babel" / "v1"

    def test_defaults_to_home_cache(self, monkeypatch):
        """Should default to ~/.cache if XDG_CACHE_HOME not set."""
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        cache_dir = get_cache_dir()
        assert cache_dir == Path.home() / ".cache" / "md-babel" / "v1"
