#!/usr/bin/env python3
"""Session server for persistent code execution.

This module provides a JSON-based protocol for executing code blocks
in a persistent namespace. It's designed to be run as a subprocess
by the session manager.

Protocol:
- Input: One JSON object per line: {"code": "..."}
- Output: One JSON object per line: {"ok": true, "out": "...", "err": "..."}

Usage:
    python -m md_babel_py.session_server
"""

import json
import sys
import traceback
from io import StringIO
from typing import Any


def main() -> None:
    """Main loop: read JSON commands, execute code, return JSON results."""
    namespace: dict[str, Any] = {}

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"ok": False, "out": "", "err": f"Invalid JSON: {e}"}), flush=True)
            continue

        code = request.get("code", "")
        if not code:
            print(json.dumps({"ok": True, "out": "", "err": ""}), flush=True)
            continue

        # Capture stdout and stderr
        stdout_capture = StringIO()
        stderr_capture = StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            # Compile and execute
            # Use 'exec' mode for statements, but try 'eval' first for expressions
            try:
                # Try to evaluate as expression (for things like "x + 1")
                result = eval(compile(code, "<block>", "eval"), namespace)
                if result is not None:
                    print(repr(result))
            except SyntaxError:
                # Not an expression, execute as statements
                exec(compile(code, "<block>", "exec"), namespace)

            response = {
                "ok": True,
                "out": stdout_capture.getvalue(),
                "err": stderr_capture.getvalue(),
            }
        except Exception:
            response = {
                "ok": False,
                "out": stdout_capture.getvalue(),
                "err": traceback.format_exc(),
            }
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
