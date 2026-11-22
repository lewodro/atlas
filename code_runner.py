"""In-process policy for `code_execute`.

Executed as `python -I -S code_runner.py` with code on stdin. An audit hook
denies network, subprocesses, dynamic loading and file access outside the
configured workspace. Resource limits are applied by the parent process.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.realpath(os.environ.get("ATLAS_WORKSPACE", os.getcwd()))
DENIED_PREFIXES = (
    "socket", "http", "urllib", "subprocess", "multiprocessing",
    "ctypes", "os.system", "os.exec", "os.spawn", "os.fork",
)
BLOCKED_IMPORTS = {"socket", "subprocess", "multiprocessing", "ctypes", "requests", "urllib", "http"}


def _allowed_path(path: str) -> bool:
    try:
        resolved = os.path.realpath(path if os.path.isabs(path) else os.path.join(ROOT, path))
    except OSError:
        return False
    return resolved == ROOT or resolved.startswith(ROOT + os.sep)


def audit(event, args):
    if event == "import" and args and args[0] in BLOCKED_IMPORTS:
        raise PermissionError(f"blocked import: {args[0]}")
    for prefix in DENIED_PREFIXES:
        if event.startswith(prefix):
            raise PermissionError(f"blocked by Atlas policy: {event}")
    if event == "open":
        path = args[0]
        if isinstance(path, (str, bytes, os.PathLike)) and not _allowed_path(os.fspath(path)):
            raise PermissionError("blocked: file outside workspace")


sys.addaudithook(audit)

code = sys.stdin.read()
namespace = {"__name__": "__atlas_sandbox__", "__builtins__": __builtins__}
try:
    exec(compile(code, "<atlas-code>", "exec"), namespace)
except Exception as exc:
    print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
    raise SystemExit(1)
