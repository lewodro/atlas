"""Allowlisted terminal tool for the configured workspace.

This is NOT a shell. No pipes, redirects, chaining, globs, env vars or arbitrary
executables. Only the few commands below run, with fixed flags, a timeout and
capped output. Paths are confined by fstools._safe_path().
"""

from __future__ import annotations

import shlex
import subprocess

import fstools

MAX_OUTPUT = 12000
TIMEOUT = 10
BAAD = set(";|&$><`\\!*?")


def allowed() -> str:
    return "ls, pwd, cat, tree, git status, git log, git diff, git branch"


def run(command: str) -> str:
    raw = str(command or "").strip()
    if not raw:
        raise fstools.ToolError("empty command")
    if any(char in BAAD for char in raw):
        raise fstools.ToolError("shell metacharacters are not allowed")
    try:
        parts = shlex.split(raw)
    except ValueError as exc:
        raise fstools.ToolError("could not parse command") from exc
    if not parts:
        raise fstools.ToolError("empty command")

    root = str(fstools.workspace())
    # Small models often emit "git_status" instead of "git status".
    parts = [word.replace("_", " ") for word in parts]
    parts = [piece for word in parts for piece in word.split(" ") if piece]
    if not parts:
        raise fstools.ToolError("empty command")
    name = parts[0].lower()
    rest = parts[1:]

    if name == "pwd":
        return root
    if name == "ls":
        path = fstools._safe_path(rest[0]) if rest else fstools.workspace()
        return _execute(["ls", "-la", str(path)], root)
    if name == "cat":
        if len(rest) != 1:
            raise fstools.ToolError("cat takes exactly one path")
        return fstools.read(rest[0])
    if name == "tree":
        return _tree(rest[0] if rest else ".")
    if name == "git":
        return _git(rest, root)
    raise fstools.ToolError(
        f"command {name!r} is not allowed. Allowed: {allowed()}"
    )


def _execute(argv: list[str], cwd: str) -> str:
    try:
        result = subprocess.run(
            argv, cwd=cwd, capture_output=True, text=True,
            timeout=TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise fstools.ToolError(f"command failed: {type(exc).__name__}") from exc
    if result.returncode:
        raise fstools.ToolError((result.stderr or "command failed").strip()[:300])
    return (result.stdout or "").strip()[:MAX_OUTPUT] or "(no output)"


def _tree(path: str) -> str:
    root = fstools._safe_path(path)
    lines = [str(root.relative_to(fstools.workspace()) or ".")]
    count = 0
    for current, dirs, files in root.walk():
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))[:40]
        for name in sorted(dirs + sorted(f for f in files if not f.startswith("."))):
            item = current / name
            prefix = "  " * len(item.relative_to(root).parts)
            lines.append(f"{prefix}{name}{'/' if item.is_dir() else ''}")
            count += 1
            if count >= 120:
                lines.append("… (truncated)")
                return "\n".join(lines)
    return "\n".join(lines)


def _git(rest: list[str], cwd: str) -> str:
    if not rest:
        raise fstools.ToolError("git needs a subcommand")
    sub = rest[0].lower().replace("_", " ")
    if " " in sub:
        rest = sub.split() + rest[1:]
        sub, args = rest[0].lower(), rest[1:]
    else:
        args = rest[1:]
    if sub == "status":
        if args and args != ["--short"]:
            raise fstools.ToolError("git status accepts only --short")
        argv = ["git", "status", "--short"] if args else ["git", "status"]
    elif sub == "log":
        count = 8
        if args:
            if len(args) == 2 and args[0] in ("-n", "--max-count") and args[1].isdigit():
                count = max(1, min(int(args[1]), 30))
            elif args == ["--oneline"]:
                count = 8
            else:
                raise fstools.ToolError("git log accepts --oneline or -n N")
        argv = ["git", "log", "--oneline", "-n", str(count)]
    elif sub == "diff":
        if args and args != ["--stat"]:
            raise fstools.ToolError("git diff accepts only --stat")
        argv = ["git", "diff", "--stat"] if args else ["git", "diff"]
    elif sub == "branch":
        if args:
            raise fstools.ToolError("git branch accepts no arguments")
        argv = ["git", "branch"]
    else:
        raise fstools.ToolError(f"git {sub} is not allowed")
    return _execute(argv, cwd)
