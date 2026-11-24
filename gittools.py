"""Read-only Git tools for the configured workspace.

No shell, no user-controlled arguments except a validated integer, and only
status/diff/log. No add, commit, push, reset, rebase or force anything.
"""

from __future__ import annotations

import subprocess

import fstools

MAX_DIFF = 8000


def root() -> str:
    return str(fstools.workspace())


def is_repo() -> bool:
    try:
        return (fstools.workspace() / ".git").exists()
    except fstools.ToolError:
        return False


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise fstools.ToolError((result.stderr or "git failed").strip()[:300])
    return result.stdout


def status_info() -> dict:
    if not is_repo():
        return {"repo": "", "branch": "", "dirty": False, "changed": 0, "is_git": False}
    output = _git("status", "--porcelain=v1", "-b")
    lines = [line for line in output.splitlines() if line.strip()]
    branch = ""
    if lines and lines[0].startswith("## "):
        branch = lines[0][3:].split("...")[0].strip()
        lines = lines[1:]
    return {
        "repo": fstools.workspace().name,
        "branch": branch,
        "dirty": bool(lines),
        "changed": len(lines),
        "is_git": True,
    }


def status_text() -> str:
    info = status_info()
    if not info["is_git"]:
        return "No Git repository in the configured workspace."
    state = "dirty" if info["dirty"] else "clean"
    return (f"Repository {info['repo']} · branch {info['branch'] or '(detached)'} · "
            f"{state} · {info['changed']} changed file(s)")


def diff_text() -> str:
    if not is_repo():
        return "No Git repository in the configured workspace."
    stat = _git("diff", "--stat").strip() or "(no unstaged changes)"
    patch = _git("diff").strip() or "(no unstaged changes)"
    return f"Diff stat:\n{stat}\n\nPatch (truncated to {MAX_DIFF} chars):\n{patch[:MAX_DIFF]}"


def log_text(limit: int = 8) -> str:
    if not is_repo():
        return "No Git repository in the configured workspace."
    count = max(1, min(int(limit), 30))
    return _git("log", "--oneline", "-n", str(count)).strip() or "(no commits)"


def init_repo() -> str:
    """Initialize a Git repository in the workspace root. Safe, no flags."""
    target = fstools.workspace()
    if is_repo():
        return f"Workspace is already a Git repository: {target.name}"
    result = subprocess.run(
        ["git", "init", "-q"], cwd=str(target),
        capture_output=True, text=True, timeout=10, check=False,
    )
    if result.returncode:
        raise fstools.ToolError((result.stderr or "git init failed").strip()[:300])
    return f"Initialized Git repository at {target}"
