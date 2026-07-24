"""Poll-based file watching for md-babel-py.

Changes are detected by hashing file contents rather than by tracking mtimes or
inodes. Editors that save via write-temp-then-rename, ``cp`` (with or without
``-p``), and ``git checkout`` all leave a different inode or an unchanged mtime,
so bytes are the only signal worth trusting.

Hashing also solves the self-trigger problem: md-babel rewrites the very file it
just read, which a naive watcher would see as a fresh edit and re-run forever.
Recording each file's hash *after* processing makes that write a no-op.
"""

import hashlib
import logging
import time
from collections.abc import Callable, Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 1.0


def hash_file(path: Path) -> str | None:
    """SHA-256 of the file's bytes, or None if it cannot be read right now."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def snapshot(files: Iterable[Path]) -> dict[Path, str]:
    """Map each readable file to the hash of its current contents."""
    hashes: dict[Path, str] = {}
    for path in files:
        digest = hash_file(path)
        if digest is not None:
            hashes[path] = digest
    return hashes


def watch(
    collect: Callable[[], list[Path]],
    process: Callable[[Path], None],
    interval: float = DEFAULT_INTERVAL,
    run_initially: bool = True,
) -> None:
    """Poll the files returned by `collect` and `process` those whose contents change.

    A change must hold steady for two consecutive polls before it is acted on, so
    a file still being written (a large `cp`, a slow editor flush) is never parsed
    half-copied and written back truncated.

    Args:
        collect: Returns the current set of files to watch, called every poll so
            files created or deleted under a watched directory are picked up.
        process: Called with each file whose contents changed.
        interval: Seconds between polls.
        run_initially: Process every file once at startup before watching.
    """
    processed: dict[Path, str] = {}  # hash as of the end of the last process() call
    settling: dict[Path, str] = {}  # changed, awaiting a second identical poll
    first_pass = True

    while True:
        current = snapshot(collect())

        for gone in processed.keys() - current.keys():
            del processed[gone]
        for gone in settling.keys() - current.keys():
            del settling[gone]

        if first_pass:
            first_pass = False
            if run_initially:
                changed = sorted(current)
            else:
                processed.update(current)
                changed = []
        else:
            changed = []
            for path, digest in sorted(current.items()):
                if processed.get(path) == digest:
                    settling.pop(path, None)  # our own write, or reverted
                elif settling.get(path) == digest:
                    del settling[path]
                    changed.append(path)
                else:
                    settling[path] = digest  # wait for it to stop moving

        for path in changed:
            process(path)
            # Re-hash after processing: this is the write we must not react to.
            written = hash_file(path)
            if written is not None:
                processed[path] = written

        time.sleep(interval)
