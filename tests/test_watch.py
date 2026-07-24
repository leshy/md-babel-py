"""Tests for --watch change detection."""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from md_babel_py.watch import hash_file, snapshot, watch


class _Stop(Exception):
    """Breaks out of watch()'s infinite loop at a known poll count."""


def drive(
    files: list[Path],
    process,
    polls: int,
    run_initially: bool = True,
    collect=None,
) -> None:
    """Run watch() for a fixed number of polls, then stop it."""
    remaining = {"n": polls}

    def _collect() -> list[Path]:
        if remaining["n"] <= 0:
            raise _Stop
        remaining["n"] -= 1
        return collect() if collect else [f for f in files if f.exists()]

    with pytest.raises(_Stop):
        watch(_collect, process, interval=0, run_initially=run_initially)


def test_hash_file_returns_none_for_missing(tmp_path):
    """An unreadable file hashes to None rather than raising."""
    assert hash_file(tmp_path / "nope.md") is None


def test_snapshot_skips_unreadable(tmp_path):
    """snapshot() includes only the files it could read."""
    present = tmp_path / "a.md"
    present.write_text("a")
    result = snapshot([present, tmp_path / "missing.md"])
    assert list(result) == [present]


def test_processes_everything_at_startup(tmp_path):
    """run_initially processes each file once, without waiting for a change."""
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("a")
    b.write_text("b")

    seen = []
    drive([a, b], seen.append, polls=3)

    assert sorted(seen) == sorted([a, b])


def test_run_initially_false_waits_for_a_change(tmp_path):
    """Without run_initially, an untouched file is never processed."""
    doc = tmp_path / "doc.md"
    doc.write_text("original")

    seen = []
    drive([doc], seen.append, polls=4, run_initially=False)

    assert seen == []


def test_self_write_does_not_retrigger(tmp_path):
    """A file rewritten by process() must not be seen as a new edit."""
    doc = tmp_path / "doc.md"
    doc.write_text("```python\nprint(1)\n```\n")

    seen = []

    def process(path: Path) -> None:
        seen.append(path)
        # Exactly what md-babel does: rewrite the file it was handed.
        path.write_text(path.read_text() + "\n```results\n1\n```\n")

    drive([doc], process, polls=8)

    assert seen == [doc], "self-write triggered a re-run"


def test_edit_is_processed(tmp_path):
    """A real edit is picked up after it settles."""
    doc = tmp_path / "doc.md"
    doc.write_text("one")

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        if polls["n"] == 2:
            doc.write_text("two")
        return [doc]

    drive([doc], seen.append, polls=6, collect=collect)

    assert seen == [doc, doc]


def test_change_must_settle_before_processing(tmp_path):
    """A file still being written is not processed until it stops changing."""
    doc = tmp_path / "doc.md"
    doc.write_text("start")

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        # Contents differ on every poll: a copy that never finishes.
        if polls["n"] >= 2:
            doc.write_text("x" * polls["n"])
        return [doc]

    drive([doc], seen.append, polls=6, collect=collect)

    # Only the startup run: nothing was stable long enough to act on.
    assert seen == [doc]


def test_detects_replacement_with_new_inode(tmp_path):
    """cp/mv over the file (new inode) is still detected."""
    doc = tmp_path / "doc.md"
    doc.write_text("original")
    original_inode = doc.stat().st_ino

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        if polls["n"] == 2:
            tmp = tmp_path / "incoming"
            tmp.write_text("replaced")
            tmp.replace(doc)  # atomic rename, new inode
        return [doc]

    drive([doc], seen.append, polls=6, collect=collect)

    assert doc.stat().st_ino != original_inode
    assert seen == [doc, doc]


def test_detects_change_that_preserves_mtime(tmp_path):
    """`cp -p`-style writes that restore the old mtime are still detected."""
    doc = tmp_path / "doc.md"
    doc.write_text("original")
    stat = doc.stat()

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        if polls["n"] == 2:
            doc.write_text("different content, same timestamps")
            os.utime(doc, (stat.st_atime, stat.st_mtime))
        return [doc]

    drive([doc], seen.append, polls=6, collect=collect)

    assert seen == [doc, doc], "mtime-preserving edit was missed"


def test_identical_rewrite_is_not_a_change(tmp_path):
    """Rewriting a file with the same bytes is not an edit."""
    doc = tmp_path / "doc.md"
    doc.write_text("same")

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        doc.write_text("same")
        return [doc]

    drive([doc], seen.append, polls=6, collect=collect)

    assert seen == [doc]


def test_new_file_in_watched_directory_is_picked_up(tmp_path):
    """Files created under a watched directory are processed."""
    first = tmp_path / "first.md"
    first.write_text("first")
    later = tmp_path / "later.md"

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        if polls["n"] == 2:
            later.write_text("later")
        return sorted(p for p in tmp_path.glob("*.md"))

    drive([], seen.append, polls=6, collect=collect)

    assert first in seen
    assert later in seen


def test_deleted_file_does_not_break_the_loop(tmp_path):
    """Deleting a watched file is survivable."""
    doc = tmp_path / "doc.md"
    doc.write_text("here")

    seen = []
    polls = {"n": 0}

    def collect() -> list[Path]:
        polls["n"] += 1
        if polls["n"] == 2:
            doc.unlink()
        return [doc] if doc.exists() else []

    drive([doc], seen.append, polls=6, collect=collect)

    assert seen == [doc]


def test_watch_cli_reruns_on_edit(tmp_path):
    """End to end: --watch runs, re-runs on an edit, and does not loop on its own write."""
    doc = tmp_path / "doc.md"
    doc.write_text('```python\nprint("FIRST")\n```\n')

    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")

    proc = subprocess.Popen(
        [
            "python", "-m", "md_babel_py.cli", "run", str(doc),
            "--watch", "--watch-interval", "0.1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    # Every processed file logs an "Executing ... block" line, so counting them
    # counts runs -- including a run that produced no visible change.
    runs: list[str] = []

    def drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            if "Executing" in line:
                runs.append(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()

    def result_text() -> str:
        """Whatever md-babel wrote into the results fence, or "" if there is none."""
        text = doc.read_text()
        _, sep, after = text.partition("```results")
        return after if sep else ""

    def wait_for(predicate, what: str) -> None:
        deadline = time.time() + 20
        while not predicate():
            assert time.time() < deadline, what
            assert proc.poll() is None, "watcher exited early"
            time.sleep(0.05)

    try:
        wait_for(lambda: "FIRST" in result_text(), "initial run never happened")
        assert len(runs) == 1

        doc.write_text('```python\nprint("SECOND")\n```\n')
        wait_for(lambda: "SECOND" in result_text(), "edit was never processed")

        # Room for the watcher to react to its own write, if it were going to.
        time.sleep(1.5)
        assert len(runs) == 2, f"watcher re-triggered on its own write: {runs}"
        assert doc.read_text().count("```results") == 1
        assert proc.poll() is None, "watcher should still be running"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        reader.join(timeout=5)
