#!/usr/bin/env python3
"""Session server for persistent code execution.

This module provides a JSON-based protocol for executing code blocks
in a persistent namespace. It's designed to be run as a subprocess
by the session manager.

Protocol:
- Input: One JSON object per line: {"code": "..."}
- Output: One JSON object per line. Possible event shapes:
    {"type": "chunk", "stream": "out"|"err", "data": "..."}
    {"type": "result", "ok": true|false, "out": "...", "err": "..."}

  Multiple "chunk" events may stream while code is running; exactly one
  "result" event terminates each request and contains the full captured
  out/err for convenience (the chunks already concatenate to the same
  text, but the result is the canonical record).

Usage:
    python -m md_babel_py.session_server
"""

import json
import sys
import traceback
from io import StringIO
from typing import Any


class _TeeStream:
    """File-like writer that mirrors writes to a StringIO buffer and emits
    a JSON 'chunk' event on the server's real stdout for each write."""

    def __init__(self, buffer: StringIO, stream_name: str, real_stdout: Any) -> None:
        self._buffer = buffer
        self._stream_name = stream_name
        self._real_stdout = real_stdout

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            data = str(data)
        if data:
            self._buffer.write(data)
            event = json.dumps({
                "type": "chunk",
                "stream": self._stream_name,
                "data": data,
            })
            self._real_stdout.write(event + "\n")
            self._real_stdout.flush()
        return len(data)

    def flush(self) -> None:
        try:
            self._real_stdout.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False


def main() -> None:
    """Main loop: read JSON commands, execute code, return JSON results."""
    namespace: dict[str, Any] = {}
    real_stdout = sys.stdout

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            real_stdout.write(json.dumps({
                "type": "result",
                "ok": False,
                "out": "",
                "err": f"Invalid JSON: {e}",
            }) + "\n")
            real_stdout.flush()
            continue

        code = request.get("code", "")
        if not code:
            real_stdout.write(json.dumps({
                "type": "result",
                "ok": True,
                "out": "",
                "err": "",
            }) + "\n")
            real_stdout.flush()
            continue

        # Capture stdout and stderr while also emitting live chunk events.
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        try:
            sys.stdout = _TeeStream(stdout_capture, "out", real_stdout)
            sys.stderr = _TeeStream(stderr_capture, "err", real_stdout)

            # Try to evaluate as expression first; fall back to exec.
            try:
                result = eval(compile(code, "<block>", "eval"), namespace)
                if result is not None:
                    print(repr(result))
            except SyntaxError:
                exec(compile(code, "<block>", "exec"), namespace)

            response = {
                "type": "result",
                "ok": True,
                "out": stdout_capture.getvalue(),
                "err": stderr_capture.getvalue(),
            }
        except Exception:
            response = {
                "type": "result",
                "ok": False,
                "out": stdout_capture.getvalue(),
                "err": traceback.format_exc(),
            }
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        real_stdout.write(json.dumps(response) + "\n")
        real_stdout.flush()


if __name__ == "__main__":
    main()
