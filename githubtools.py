"""Read-only GitHub tools via the local `gh` CLI.

No shell, no writes, no network unless the tool is called. Repositories must
be in a local allowlist (data/github.json). Nothing here stores credentials.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import fstools

FILE = fstools.CONFIG_FILE.parent / "github.json"
DEFAULT_REPOS = ["lewodro/atlas"]
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _config() -> dict:
    if FILE.exists():
        try:
            value = json.loads(FILE.read_text())
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def allowed_repos() -> list[str]:
    rows = _config().get("repos") or DEFAULT_REPOS
    return [str(r) for r in rows if REPO_RE.match(str(r))]


def available() -> bool:
    return shutil.which("gh") is not None


def _repo(value: str) -> str:
    repo = str(value or "").strip() or (allowed_repos() or [None])[0]
    if not repo or not REPO_RE.match(repo):
        raise fstools.ToolError("repo must look like owner/name")
    if repo not in allowed_repos():
        raise fstools.ToolError(f"repo {repo} is not in the local allowlist")
    return repo


def _api(path: str, fields: dict | None = None) -> list | dict:
    if not available():
        raise fstools.ToolError("gh CLI is not installed")
    command = ["gh", "api", path, "-X", "GET"]
    for key, value in (fields or {}).items():
        command += ["-f", f"{key}={value}"]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise fstools.ToolError(f"gh failed: {type(exc).__name__}") from exc
    if result.returncode:
        raise fstools.ToolError((result.stderr or "gh failed").strip()[:300])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise fstools.ToolError("gh returned invalid JSON") from exc


def issues(args: dict) -> str:
    repo = _repo(args.get("repo", ""))
    state = str(args.get("state", "open")).lower()
    if state not in ("open", "closed", "all"):
        raise fstools.ToolError("state must be open, closed or all")
    limit = max(1, min(int(args.get("limit", 5)), 20))
    rows = _api(f"repos/{repo}/issues", {"state": state, "per_page": limit})
    if not isinstance(rows, list):
        return "No issues returned."
    lines = [f"{repo} issues ({state}):"]
    for row in rows:
        if "pull_request" in row:
            continue
        lines.append(f"#{row.get('number')} [{row.get('state')}] {row.get('title', '')} — {row.get('html_url', '')}")
    return "\n".join(lines[:limit])


def pulls(args: dict) -> str:
    repo = _repo(args.get("repo", ""))
    state = str(args.get("state", "open")).lower()
    if state not in ("open", "closed", "all"):
        raise fstools.ToolError("state must be open, closed or all")
    limit = max(1, min(int(args.get("limit", 5)), 20))
    rows = _api(f"repos/{repo}/pulls", {"state": state, "per_page": limit})
    if not isinstance(rows, list):
        return "No pull requests returned."
    lines = [f"{repo} pull requests ({state}):"]
    for row in rows:
        lines.append(f"#{row.get('number')} [{row.get('state')}] {row.get('title', '')} — {row.get('html_url', '')}")
    return "\n".join(lines[:limit])


def repo_info(args: dict) -> str:
    repo = _repo(args.get("repo", ""))
    data = _api(f"repos/{repo}")
    if not isinstance(data, dict):
        return "No repository returned."
    return (
        f"{data.get('full_name', repo)} · {data.get('default_branch', 'main')}\n"
        f"{str(data.get('description') or '')[:300]}\n"
        f"visibility: {data.get('visibility', 'unknown')} · stars: {data.get('stargazers_count', 0)}"
    )
