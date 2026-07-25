"""Tests for writing results as blocks finish, on top of the file as it stands."""

import os
import subprocess
import time
from pathlib import Path

import pytest

from md_babel_py.parser import block_identity, find_code_blocks, locate_block
from md_babel_py.watch import watch


SLOW = 4  # seconds a block sleeps, long enough to edit the file while it runs


def start(md_file: Path, tmp_path: Path, extra: list[str] | None = None):
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    return subprocess.Popen(
        ["python", "-m", "md_babel_py.cli", "run", str(md_file), "--no-cache"]
        + (extra or []),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def wait_until(predicate, what: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while not predicate():
        assert time.time() < deadline, what
        time.sleep(0.05)


class TestLocateBlock:
    """Re-finding a block in a document that has moved underneath it."""

    def test_finds_block_after_lines_shift(self):
        original = '```python\nprint("a")\n```\n'
        block = find_code_blocks(original)[0]

        shifted = 'new prose\n\nmore prose\n\n' + original
        found = locate_block(shifted, block_identity(block))

        assert found is not None
        assert found.code == block.code
        assert found.start_line > block.start_line

    def test_returns_none_when_block_was_edited(self):
        block = find_code_blocks('```python\nprint("a")\n```\n')[0]
        assert locate_block('```python\nprint("EDITED")\n```\n', block_identity(block)) is None

    def test_returns_none_when_block_was_removed(self):
        block = find_code_blocks('```python\nprint("a")\n```\n')[0]
        assert locate_block('just prose now\n', block_identity(block)) is None

    def test_ordinal_picks_between_identical_blocks(self):
        content = '```python\nprint("same")\n```\n\n```python\nprint("same")\n```\n'
        blocks = find_code_blocks(content)
        assert len(blocks) == 2

        first = locate_block(content, block_identity(blocks[0]), 0)
        second = locate_block(content, block_identity(blocks[1]), 1)
        assert first is not None and second is not None
        assert first.start_line == blocks[0].start_line
        assert second.start_line == blocks[1].start_line


def test_results_appear_while_later_blocks_still_run(tmp_path):
    """A block's result is written as soon as it finishes, not at the end of the run."""
    md_file = tmp_path / "doc.md"
    md_file.write_text(
        '```python\nprint("FIRST")\n```\n\n'
        f'```python\nimport time; time.sleep({SLOW}); print("SECOND")\n```\n'
    )

    proc = start(md_file, tmp_path)
    try:
        # One results fence means the first block's output landed on its own.
        wait_until(lambda: md_file.read_text().count("```results") == 1,
                   "first result was not written before the run finished")
        mid_run = md_file.read_text()
        assert proc.poll() is None, "run finished too fast to prove anything"
        assert "FIRST" in mid_run.split("```results")[1]
    finally:
        proc.wait(timeout=60)

    after = md_file.read_text()
    assert after.count("```results") == 2
    assert "FIRST" in after.split("```results")[1]
    assert "SECOND" in after.split("```results")[2]


def test_edit_made_during_a_run_is_kept(tmp_path):
    """Text written while a block runs survives the result being added."""
    md_file = tmp_path / "doc.md"
    md_file.write_text(
        f'```python\nimport time; time.sleep({SLOW}); print("RESULT")\n```\n'
    )

    proc = start(md_file, tmp_path)
    try:
        time.sleep(1)
        md_file.write_text(md_file.read_text() + "\nprose the author just typed\n")
    finally:
        proc.wait(timeout=60)

    after = md_file.read_text()
    assert "prose the author just typed" in after, "author's edit was overwritten"
    assert "RESULT" in after, "result was not written"


def test_result_for_a_block_edited_mid_run_is_dropped(tmp_path):
    """Rewriting a block while it runs must not get the old block's result."""
    md_file = tmp_path / "doc.md"
    slow_block = f'```python\nimport time; time.sleep({SLOW}); print("STALE")\n```\n'
    md_file.write_text('```python\nprint("QUICK")\n```\n\n' + slow_block)

    proc = start(md_file, tmp_path)
    try:
        time.sleep(1)
        md_file.write_text(
            md_file.read_text().replace(
                f'import time; time.sleep({SLOW}); print("STALE")',
                'print("EDITED BY AUTHOR")',
            )
        )
    finally:
        proc.wait(timeout=60)

    after = md_file.read_text()
    assert 'print("EDITED BY AUTHOR")' in after, "author's rewrite was lost"
    assert "STALE" not in after, "stale result was written onto an edited block"
    assert "QUICK" in after, "earlier block's result went missing"


def test_unsettled_file_is_processed_again(tmp_path):
    """process() returning False makes the watcher come back to the file."""
    doc = tmp_path / "doc.md"
    doc.write_text("content")

    calls: list[Path] = []

    def process(path: Path) -> bool:
        calls.append(path)
        return len(calls) > 1  # first pass reports the file as edited mid-run

    remaining = {"n": 6}

    class _Stop(Exception):
        pass

    def collect() -> list[Path]:
        if remaining["n"] <= 0:
            raise _Stop
        remaining["n"] -= 1
        return [doc]

    with pytest.raises(_Stop):
        watch(collect, process, interval=0, run_initially=True)

    assert len(calls) == 2, f"expected a second pass, got {len(calls)}"
