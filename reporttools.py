"""Bounded project test helpers for agent collaboration."""

from __future__ import annotations

import fstools
import handoff

import codetools


def project_test(path: str) -> str:
    path = str(path or "").strip()
    if not path:
        raise fstools.ToolError("path is required")
    source = fstools.read(path, max_chars=20000).split(":\n", 1)[-1]
    check = (
        "import sys\n"
        f"src = {source!r}\n"
        "try:\n"
        "    compile(src, 'project_file', 'exec')\n"
        "    print('syntax: OK')\n"
        "except SyntaxError as exc:\n"
        "    print('syntax: FAIL', exc)\n"
        "    raise SystemExit(1)\n"
    )
    result = codetools.execute(check)
    lines = [line for line in result.splitlines()
             if line.startswith(("exit:", "syntax:", "stdout:", "stderr:"))]
    return f"Test of {path}:\n" + "\n".join(lines[:8])


def test_report(results: str, issues: str = "", path: str = "TEST_REPORT.md") -> dict:
    results = str(results or "").strip()
    if not results:
        raise fstools.ToolError("results are empty")
    text = (
        "# Test report\n\n"
        f"## Results\n{results}\n\n"
        f"## Reproduced issues\n{issues or 'None reported.'}\n"
    )
    fstools.write(path, text)
    handoff.write("coder", f"Test report written to {path}. {results[:400]}"
                  + (f" Issues: {issues[:300]}" if issues else ""))
    return {
        "ok": True,
        "data": f"Wrote test report to {path} and handed findings back to coder",
        "artifact_hint": {"title": path, "kind": "markdown", "path": path},
    }
