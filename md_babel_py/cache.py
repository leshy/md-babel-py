"""Cache for code block execution results."""

import hashlib
import json
import logging
import os
from dataclasses import asdict
from pathlib import Path

from .config import EvaluatorConfig
from .parser import CodeBlock
from .types import ExecutionResult

logger = logging.getLogger(__name__)

CACHE_VERSION = "v1"


def get_cache_dir() -> Path:
    """Get the cache directory following XDG Base Directory spec."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        base = Path(xdg_cache)
    else:
        base = Path.home() / ".cache"
    return base / "md-babel" / CACHE_VERSION


def compute_cache_key(block: CodeBlock, evaluator: EvaluatorConfig) -> str:
    """Compute a cache key for a code block execution.

    The key is a hash of:
    - Code content
    - Language
    - Evaluator configuration (path, args, prefix, suffix)
    - Block params (excluding 'output' which is just destination)
    """
    key_data = {
        "code": block.code,
        "lang": block.language,
        "eval": {
            "path": evaluator.path,
            "args": evaluator.default_arguments,
            "prefix": evaluator.prefix,
            "suffix": evaluator.suffix,
            "input_extension": evaluator.input_extension,
            "default_params": evaluator.default_params,
        },
        "params": {k: v for k, v in block.params.items() if k != "output"},
    }
    key_json = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_json.encode()).hexdigest()[:16]


class Cache:
    """Cache for code block execution results.

    Stores ExecutionResult objects keyed by a hash of the code block
    and evaluator configuration. Optionally stores output file content
    for blocks that produce files.
    """

    def __init__(self, enabled: bool = True):
        """Initialize the cache.

        Args:
            enabled: Whether caching is enabled. If False, all operations are no-ops.
        """
        self.enabled = enabled
        self.cache_dir = get_cache_dir()
        self._hits = 0
        self._misses = 0

    def _ensure_dir(self) -> None:
        """Ensure the cache directory exists."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, key: str) -> Path:
        """Get the path to the metadata file for a cache key."""
        return self.cache_dir / f"{key}.json"

    def _output_path(self, key: str) -> Path:
        """Get the path to the output file for a cache key."""
        return self.cache_dir / f"{key}.out"

    def get(self, key: str, output_file: str | None = None) -> ExecutionResult | None:
        """Get a cached result.

        Args:
            key: The cache key.
            output_file: If provided and the cache contains output content,
                        restore it to this path.

        Returns:
            The cached ExecutionResult, or None if not found.
        """
        if not self.enabled:
            return None

        meta_path = self._meta_path(key)
        if not meta_path.exists():
            self._misses += 1
            return None

        try:
            with open(meta_path) as f:
                data = json.load(f)

            result = ExecutionResult(
                stdout=data["stdout"],
                stderr=data["stderr"],
                success=data["success"],
                error_message=data.get("error_message"),
            )

            # Restore output file if needed
            if output_file and data.get("has_output"):
                output_cache = self._output_path(key)
                if output_cache.exists():
                    # Ensure parent directory exists
                    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
                    # Copy cached output to destination
                    Path(output_file).write_bytes(output_cache.read_bytes())
                    logger.debug(f"Restored cached output to {output_file}")

            self._hits += 1
            return result

        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.debug(f"Cache read error for {key}: {e}")
            self._misses += 1
            return None

    def put(
        self,
        key: str,
        result: ExecutionResult,
        output_file: str | None = None,
    ) -> None:
        """Store a result in the cache.

        Args:
            key: The cache key.
            result: The execution result to cache.
            output_file: If provided and exists, cache its content too.
        """
        if not self.enabled:
            return

        self._ensure_dir()

        has_output = False
        if output_file:
            output_path = Path(output_file)
            if output_path.exists():
                try:
                    self._output_path(key).write_bytes(output_path.read_bytes())
                    has_output = True
                except OSError as e:
                    logger.debug(f"Failed to cache output file: {e}")

        data = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.success,
            "error_message": result.error_message,
            "has_output": has_output,
        }

        try:
            with open(self._meta_path(key), "w") as f:
                json.dump(data, f)
        except OSError as e:
            logger.debug(f"Failed to write cache: {e}")

    def clear(self) -> int:
        """Clear all cached entries.

        Returns:
            Number of entries cleared.
        """
        if not self.cache_dir.exists():
            return 0

        count = 0
        for path in self.cache_dir.iterdir():
            if path.is_file():
                path.unlink()
                count += 1
        return count

    @property
    def stats(self) -> dict[str, int]:
        """Get cache statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
        }
