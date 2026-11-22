"""Bounded Python code execution in a restricted subprocess.

This is not a shell. Code runs with -I -S, a policy audit hook, OS resource
limits, a timeout and capped output. Files are confined to the workspace.
"""

from __future__ import annotations

import os
import resource
import subprocess
import sys

import config
import fstools

MAX_OUTPUT = 8000
TIMEOUT = 12


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def available() -> bool:
    return (config.ROOT / "code_runner.py").exists()


def execute(code: str) -> str:
    if not available():
        raise fstools.ToolError("code runner is missing")
    code = str(code or "")
    if not code.strip():
        raise fstools.ToolError("empty code")
    if len(code) > 20000:
        raise fstools.ToolError("code is too long")
    try:
        workspace = str(fstools.workspace())
    except fstools.ToolError:
        workspace = str(config.ROOT)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONUNBUFFERED": "1",
        "ATLAS_WORKSPACE": workspace,
    }
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(config.ROOT / "code_runner.py")],
            input=code,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=workspace,
            env=env,
            preexec_fn=_limits,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise fstools.ToolError(f"code timed out after {TIMEOUT}s")
    except (OSError, ValueError) as exc:
        raise fstools.ToolError(f"runner failed: {type(exc).__name__}")

    out = (result.stdout or "").strip()[:MAX_OUTPUT]
    err = (result.stderr or "").strip()[:MAX_OUTPUT]
    return (
        f"exit: {result.returncode}\n"
        f"stdout:\n{out or '(empty)'}\n"
        f"stderr:\n{err or '(empty)'}"
    )
