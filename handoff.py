"""Agent-to-agent handoff notes in a shared workspace.

A handoff is a plain Markdown file agents can read and append to. It is not
memory, not a chat log, and not executable. Both workers must point at the
same workspace to exchange files.
"""

from __future__ import annotations

import time

import fstools

HANDOFF = "HANDOFF.md"


def available() -> bool:
    return True


def write(to: str, message: str, files: str | list[str] | None = None) -> dict:
    to = str(to or "all").strip()
    message = str(message or "").strip()
    if not message:
        raise fstools.ToolError("handoff message is empty")
    files = files or []
    if isinstance(files, str):
        files = [part.strip() for part in files.split(",") if part.strip()]

    existing = ""
    try:
        existing = fstools.read(HANDOFF, max_chars=50000).split(":\n", 1)[-1]
    except fstools.ToolError:
        pass

    sender = fstools.workspace().name
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = (
        f"\n---\n## {stamp} · {sender} → {to}\n\n{message}\n"
        + ("\nFiles:\n" + "\n".join(f"- {name}" for name in files) if files else "")
        + "\n"
    )
    fstools.write(HANDOFF, (existing + entry).strip() + "\n")
    return {
        "ok": True,
        "data": f"Wrote handoff to {to} in {HANDOFF}",
        "artifact_hint": {"title": HANDOFF, "kind": "markdown", "path": HANDOFF},
    }


def read() -> str:
    try:
        return fstools.read(HANDOFF, max_chars=50000)
    except fstools.ToolError:
        return "No handoff notes yet."
