"""Filesystem tools with workspace confinement.

Nothing outside the configured workspace can be read or written. Hidden files
and directories (.env, .git, .ssh, …), key material and symlinks are refused.
There is no delete, move, glob or shell primitive — only read, write and list.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

import config

CONFIG_FILE = config.ROOT_DATA / "tools.json"
MAX_BYTES = 256_000
DENIED_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials.json"}
DENIED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".npmrc")


class ToolError(Exception):
    pass


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(**patch) -> dict:
    data = load_config()
    for key, value in patch.items():
        if value is None or str(value).strip() == "":
            data.pop(key, None)
        else:
            data[key] = str(value).strip()
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def configure_workspace(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        raise ToolError("workspace path is empty")
    expanded = Path(raw).expanduser().resolve()
    if not expanded.is_dir():
        raise ToolError("workspace must be an existing directory")
    save_config(workspace=str(expanded))
    return str(expanded)


def workspace() -> Path:
    raw = load_config().get("workspace") or os.getenv("ATLAS_WORKSPACE", "")
    if not raw:
        raise ToolError(
            "Filesystem workspace is not configured. "
            "Run: atlas tools configure --workspace /path/to/project"
        )
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise ToolError("configured workspace no longer exists")
    return root


def _safe_path(path: str) -> Path:
    root = workspace()
    raw = str(path or "").strip()
    if not raw:
        raise ToolError("path is empty")
    if raw in ("/", "./"):
        raw = "."
    candidate = Path(raw)
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not target.is_relative_to(root):
        raise ToolError("path escapes the workspace")
    for part in target.relative_to(root).parts:
        if part.startswith(".") or part.lower() in DENIED_NAMES:
            raise ToolError(f"hidden or sensitive path refused: {part}")
    if target.name.lower().endswith(DENIED_SUFFIXES):
        raise ToolError("key or credential file refused")
    if target.is_symlink():
        raise ToolError("symlinks are refused")
    return target


def read(path: str, max_chars: int = MAX_BYTES) -> str:
    target = _safe_path(path)
    if not target.is_file():
        raise ToolError("not a file inside the workspace")
    size = target.stat().st_size
    if size > MAX_BYTES:
        raise ToolError("file is too large to read")
    raw = target.read_bytes()
    if b"\x00" in raw:
        raise ToolError("binary file refused")
    text = raw.decode("utf-8", errors="replace")[: max(200, min(int(max_chars), MAX_BYTES))]
    return f"Read {target.relative_to(workspace())} ({len(text)} chars):\n{text}"


def write(path: str, content: str) -> str:
    if not isinstance(content, str) or "\x00" in content:
        raise ToolError("content must be text without null bytes")
    if len(content.encode("utf-8")) > MAX_BYTES:
        raise ToolError("content is too large")
    target = _safe_path(path)
    if target.exists() and not target.is_file():
        raise ToolError("target is not a regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.parent.resolve().is_relative_to(workspace()):
        raise ToolError("parent escapes the workspace")

    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target.parent, prefix=".atlas-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content.encode("utf-8"))
        os.chmod(temporary, mode)
        if target.is_symlink():
            raise ToolError("symlinks are refused")
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return f"Wrote {len(content)} chars to {target.relative_to(workspace())}"


def list_dir(path: str = ".") -> str:
    target = _safe_path(path or ".")
    if not target.is_dir():
        raise ToolError("not a directory inside the workspace")
    rows = []
    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.name.startswith("."):
            continue
        kind = "dir" if entry.is_dir() else "file"
        size = "" if entry.is_dir() else f" {entry.stat().st_size}b"
        rows.append(f"{kind:4} {entry.name}{size}")
        if len(rows) >= 100:
            break
    return f"Listed {target.relative_to(workspace())}:\n" + "\n".join(rows[:100]) or "empty"


def status() -> dict:
    data = load_config()
    configured = bool(data.get("workspace") or os.getenv("ATLAS_WORKSPACE"))
    result = {
        "available": configured,
        "workspace": data.get("workspace") or os.getenv("ATLAS_WORKSPACE", ""),
    }
    if configured:
        try:
            result["workspace"] = str(workspace())
        except ToolError as exc:
            result["available"] = False
            result["error"] = str(exc)
    return result
