"""Shared drive for Atlas agent instances.

Each worker has its own workspace and memory, but every instance can also see
one shared folder. That is where agents leave files for each other and where
the orchestrator writes goals, handoffs and results.

The folder defaults to data/shared and can be moved with ATLAS_SHARED_DRIVE.
Access is confined exactly like fstools: no absolute paths, no '..', no hidden
files, no symlinks, text only.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import config
import fstools

HANDOFF = "HANDOFF.md"
MAX_BYTES = 256_000
_registered = False


def drive() -> Path:
    raw = os.getenv("ATLAS_SHARED_DRIVE", "").strip()
    root = Path(raw).expanduser().resolve() if raw else config.ROOT_DATA / "shared"
    return root


def safe(path: str) -> Path:
    root = drive()
    value = str(path or "").strip() or "."
    candidate = Path(value)
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not target.is_relative_to(root):
        raise fstools.ToolError("shared path escapes the drive")
    for part in target.relative_to(root).parts:
        if part.startswith(".") or part.lower() in fstools.DENIED_NAMES:
            raise fstools.ToolError(f"hidden or sensitive shared path refused: {part}")
    if target.name.lower().endswith(fstools.DENIED_SUFFIXES):
        raise fstools.ToolError("key or credential file refused")
    if target.is_symlink():
        raise fstools.ToolError("symlinks are refused")
    return target


def run(args: dict) -> str:
    action = str((args or {}).get("action") or "").lower()
    path = str((args or {}).get("path") or ".")
    target = safe(path)

    if action == "list":
        root = drive()
        if not root.exists():
            return "Shared drive is empty (not created yet)."
        rows = []
        for entry in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            if entry.name.startswith("."):
                continue
            kind = "dir" if entry.is_dir() else "file"
            size = "" if entry.is_dir() else f" {entry.stat().st_size}b"
            rows.append(f"{kind:4} {entry.relative_to(root)}{size}")
            if len(rows) >= 100:
                break
        return "Shared drive:\n" + ("\n".join(rows) or "(empty)")

    if action == "read":
        if not target.is_file():
            raise fstools.ToolError("not a file on the shared drive")
        if target.stat().st_size > MAX_BYTES:
            raise fstools.ToolError("shared file is too large")
        text = target.read_bytes().decode("utf-8", errors="replace")
        return f"Shared {path} ({len(text)} chars):\n{text[:MAX_BYTES]}"

    if action == "write":
        content = str((args or {}).get("content") or "")
        if not isinstance(content, str) or "\x00" in content:
            raise fstools.ToolError("content must be text without null bytes")
        if len(content.encode("utf-8")) > MAX_BYTES:
            raise fstools.ToolError("shared file is too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb", dir=target.parent, prefix=".atlas-share-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content.encode("utf-8"))
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return f"Wrote {len(content)} chars to shared {target.relative_to(drive())}"

    if action == "mkdir":
        target.mkdir(parents=True, exist_ok=True)
        return f"Created shared directory {target.relative_to(drive())}"

    if action == "handoff":
        note = str((args or {}).get("note") or "").strip()
        if not note:
            raise fstools.ToolError("handoff needs a note")
        from datetime import datetime, timezone

        target = safe(HANDOFF)
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        who = os.getenv("ATLAS_PROFILE", "agent")
        previous = target.read_text(encoding="utf-8") if target.exists() else "# Handoff\n"
        target.write_text(
            f"{previous.rstrip()}\n\n- {stamp} [{who}] {note[:1000]}\n", encoding="utf-8"
        )
        return f"Handoff recorded in {HANDOFF}"

    raise fstools.ToolError(
        "share action must be list, read, write, mkdir or handoff"
    )


def register() -> int:
    global _registered
    if _registered:
        return 0
    _registered = True
    import registry

    registry.register(registry.ToolSpec(
        id="share",
        description=(
            "Shared drive visible to every Atlas agent instance. Actions: list, "
            "read, write, mkdir, handoff (append a message to HANDOFF.md). "
            "Path is relative to the shared drive."
        ),
        parameters={"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["list", "read", "write", "mkdir", "handoff"]},
            "path": {"type": "string"},
            "content": {"type": "string"},
            "note": {"type": "string"},
        }, "required": ["action"]},
        handler=run,
        category="shared",
        permission="ALLOW",
        provider="atlas",
    ))
    return 1
