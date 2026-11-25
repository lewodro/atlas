"""What Atlas sends off the machine — recorded, previewable, and guarded.

Every model call writes a small redacted line to data/egress.jsonl: destination
host, model, message roles and sizes, tool names, and flags for local paths /
URLs / memory text that appeared in the payload. Message contents are never
stored here.

Remote endpoints are blocked until the user explicitly opts in, either with
ATLAS_ALLOW_REMOTE=1 or by selecting a hosted provider with `atlas models
--provider NAME`. That makes "which data do you send?" a concrete answer
instead of a promise.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import config
import providers

LEDGER = config.ROOT_DATA / "egress.jsonl"
SETTINGS = config.ROOT_DATA / "settings.json"

_PATH = re.compile(r"(?:~/|/Users/|/home/|[A-Za-z]:\\|\\\\?\\\\[^\\]+\\)")
_URL = re.compile(r"https?://", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_MEMORY = re.compile(r"\b(?:PROFILE|GOAL:|MEMORY|PERSONAL NOTE)\b", re.I)


def _host(base_url: str) -> str:
    try:
        return urlparse(str(base_url or "")).netloc or str(base_url or "")
    except ValueError:
        return str(base_url or "")


def _flags(messages: list[dict]) -> dict:
    text = "\n".join(str(item.get("content") or "") for item in messages or [])
    return {
        "local_paths": bool(_PATH.search(text)),
        "urls": bool(_URL.search(text)),
        "emails": bool(_EMAIL.search(text)),
        "memory_markers": bool(_MEMORY.search(text)),
    }


def preview(messages: list[dict], tools: list[dict] | None,
            base_url: str, model: str) -> dict:
    """A payload summary you can inspect before anything is sent."""
    roles: dict[str, int] = {}
    chars = 0
    for item in messages or []:
        role = str(item.get("role") or "unknown")
        roles[role] = roles.get(role, 0) + 1
        chars += len(str(item.get("content") or ""))
    names = []
    for tool in tools or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if isinstance(function, dict) and function.get("name"):
            names.append(str(function["name"]))
    local = providers.is_local(base_url)
    preset = providers.for_base_url(base_url)
    return {
        "destination": _host(base_url),
        "provider": (preset or {}).get("id") or ("local" if local else "custom"),
        "local": local,
        "model": model,
        "messages": roles,
        "message_chars": chars,
        "tools": sorted(set(names)),
        "flags": _flags(messages or []),
        "egress_note": (preset or {}).get("egress") or (
            "nothing leaves this machine" if local else "custom remote endpoint"
        ),
    }


def record(messages: list[dict], tools: list[dict] | None,
           base_url: str, model: str) -> dict:
    """Append a redacted ledger entry. Never raises into the caller."""
    entry = {"ts": int(time.time()), **preview(messages, tools, base_url, model)}
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return entry


def ledger(limit: int = 40) -> list[dict]:
    if not LEDGER.exists():
        return []
    try:
        return [json.loads(line) for line in
                LEDGER.read_text(encoding="utf-8").splitlines()[-limit:]]
    except (OSError, json.JSONDecodeError):
        return []


def remote_allowed() -> bool:
    if os.getenv("ATLAS_ALLOW_REMOTE", "").strip() == "1":
        return True
    try:
        saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return bool(saved.get("remote_ok"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def approve_remote() -> None:
    try:
        saved = {}
        if SETTINGS.exists():
            saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        saved["remote_ok"] = True
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, ValueError):
        pass


def guard(base_url: str) -> None:
    """Block accidental egress to an unapproved remote endpoint."""
    if providers.is_local(base_url) or remote_allowed():
        return
    raise RuntimeError(
        f"remote model endpoint {_host(base_url)} is blocked. "
        "Choose a hosted provider with 'atlas models --provider NAME' or set "
        "ATLAS_ALLOW_REMOTE=1 in .env. Prompts and tool results would be sent there."
    )
