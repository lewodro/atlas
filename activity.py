"""Activity: what have I actually been doing?

This is the "analyze my life" input. It is deliberately modest and 100% local:
no screenshots, no keylogging, no cloud.

  - git commits in the last N hours, across every repo under ~/dev
  - files modified in the last N hours (code, notes, docs)

    uv run python activity.py            # summary for the last 24h
    uv run python activity.py --scan     # also append a snapshot to data/

Nothing here leaves the machine. Settings live in config.py.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

from config import ROOT_DATA

PROJECTS = Path(os.getenv("ATLAS_PROJECTS", str(Path.home() / "dev")))

SKIP = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".next", ".nuxt", "target", "vendor", ".mypy_cache", ".ruff_cache",
    "Library", "Pods", ".gradle", ".idea", "site-packages",
}

CODE = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".rs", ".go",
    ".java", ".rb", ".sh", ".sql", ".md", ".txt", ".toml", ".yaml", ".yml",
    ".json", ".html", ".css", ".ipynb",
}


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def repos() -> list[Path]:
    found = []
    for root, dirs, _ in os.walk(PROJECTS):
        dirs[:] = [d for d in dirs if d not in SKIP]
        if ".git" in os.listdir(root):
            found.append(Path(root))
            dirs[:] = []  # don't descend into a repo
        if len(found) >= 40:
            break
    return found


def commits(hours: int = 24) -> list[str]:
    since = f"{hours} hours ago"
    lines = []
    for repo in repos():
        log = _git(repo, "log", f"--since={since}", "--pretty=format:%h %s", "--no-merges")
        for line in log.splitlines()[:8]:
            lines.append(f"{repo.name}: {line}")
    return lines


def touched(hours: int = 24, limit: int = 15) -> list[tuple[str, str]]:
    """(relative path, '2h ago') for recently modified files."""
    cutoff = (dt.datetime.now() - dt.timedelta(hours=hours)).timestamp()
    seen: list[tuple[float, Path]] = []

    for root, dirs, files in os.walk(PROJECTS):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            if Path(name).suffix not in CODE:
                continue
            path = Path(root) / name
            try:
                if path.is_relative_to(ROOT_DATA):
                    continue  # don't report Atlas's own runtime files
                mtime = path.stat().st_mtime
            except (OSError, ValueError):
                continue
            if mtime >= cutoff:
                seen.append((mtime, path))

    seen.sort(reverse=True)
    out = []
    for mtime, path in seen[:limit]:
        age = dt.datetime.now() - dt.datetime.fromtimestamp(mtime)
        hours_ago = max(0, int(age.total_seconds() // 3600))
        out.append((str(path.relative_to(PROJECTS.parent)), f"{hours_ago}h ago"))
    return out


def summary(hours: int = 24) -> str:
    """A compact digest for the model's system prompt."""
    if not PROJECTS.exists():
        return f"(no projects folder at {PROJECTS})"

    commit_lines = commits(hours)
    file_lines = touched(hours)

    parts = [f"Projects folder: {PROJECTS}"]
    parts.append(f"Commits in the last {hours}h: {len(commit_lines)}")
    parts.extend(f"  {c}" for c in commit_lines[:10])

    parts.append(f"Files touched in the last {hours}h: {len(file_lines)}")
    parts.extend(f"  {p} ({when})" for p, when in file_lines[:12])

    if not commit_lines and not file_lines:
        parts.append("No recorded activity. Either a rest day, or nothing is committed.")
    return "\n".join(parts)


def snapshot(hours: int = 24) -> Path:
    ROOT_DATA.mkdir(parents=True, exist_ok=True)
    path = ROOT_DATA / "activity.jsonl"
    record = {
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "hours": hours,
        "commits": commits(hours),
        "touched": [p for p, _ in touched(hours)],
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return path


if __name__ == "__main__":
    hours = 24
    for i, arg in enumerate(sys.argv):
        if arg == "--hours" and i + 1 < len(sys.argv):
            hours = int(sys.argv[i + 1])

    print(summary(hours))
    if "--scan" in sys.argv:
        print(f"\nappended snapshot -> {snapshot(hours)}")
