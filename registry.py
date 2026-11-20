"""One registry drives model tools, CLI, server API and the GUI.

A provider (built-in or future MCP/GitHub/etc.) registers a ToolSpec. Nothing
else hardcodes a tool list. Specs carry id, description, schema, availability,
category, permission level and provider.

Permission levels:
  ALLOW  run automatically
  ASK    needs explicit approval for that call
  DENY   never advertised, never run
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import config
import fstools
import gittools
import skills
import webtools

PERMISSIONS_FILE = config.ROOT_DATA / "permissions.json"
ACTIVITY_FILE = config.ROOT_DATA / "tool_activity.jsonl"
LOCK = threading.Lock()

LEVELS = {"ALLOW", "ASK", "DENY"}


@dataclass
class ToolSpec:
    id: str
    description: str
    parameters: dict
    handler: Callable[[dict], Any]
    category: str = "general"
    permission: str | Callable[[dict], str] = "ALLOW"
    provider: str = "atlas"
    available: Callable[[], bool] | bool = True
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": self.description[:260],
                "parameters": self.parameters,
            },
        }

    def metadata(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "schema": self.parameters,
            "category": self.category,
            "permission": (self.permission if isinstance(self.permission, str) else "ASK"),
            "provider": self.provider,
            "availability": bool(self.available() if callable(self.available) else self.available),
            "available": bool(self.available() if callable(self.available) else self.available),
            "aliases": list(self.aliases),
        }


_SPECS: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    _SPECS[spec.id] = spec
    return spec


def specs() -> dict[str, ToolSpec]:
    return dict(_SPECS)


def get(tool_id: str) -> ToolSpec | None:
    return _SPECS.get(tool_id)


def _permissions() -> dict:
    if PERMISSIONS_FILE.exists():
        try:
            value = json.loads(PERMISSIONS_FILE.read_text())
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def permission(tool_id: str, args: dict | None = None) -> str:
    override = _permissions().get(tool_id)
    if override in LEVELS:
        return override
    spec = _SPECS.get(tool_id)
    if not spec:
        return "DENY"
    level = spec.permission(args or {}) if callable(spec.permission) else spec.permission
    return level if level in LEVELS else "DENY"


def set_permission(tool_id: str, level: str) -> str:
    if level not in LEVELS:
        raise ValueError(f"permission must be one of {sorted(LEVELS)}")
    if tool_id not in _SPECS:
        raise ValueError(f"unknown tool {tool_id}")
    data = _permissions()
    data[tool_id] = level
    PERMISSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERMISSIONS_FILE.write_text(json.dumps(data, indent=2) + "\n")
    return level


def is_available(spec: ToolSpec) -> bool:
    return bool(spec.available() if callable(spec.available) else spec.available)


def definitions() -> list[dict]:
    """Small, current tool list for the local model."""
    return [
        spec.definition()
        for spec in _SPECS.values()
        if is_available(spec) and permission(spec.id) != "DENY"
    ]


def metadata() -> list[dict]:
    return [spec.metadata() for spec in _SPECS.values()]


NEEDS_APPROVAL = "NEEDS_APPROVAL"


def run(tool_id: str, args: dict | None = None, *, approved: bool = False) -> dict:
    """Execute a tool and record real activity. Always returns a structured result."""
    args = args or {}
    started = time.perf_counter()
    result: dict[str, Any] = {
        "tool": tool_id,
        "provider": _SPECS[tool_id].provider if tool_id in _SPECS else "unknown",
        "ok": False,
        "data": "",
        "error": None,
        "duration_ms": 0,
        "permission": permission(tool_id, args),
    }

    try:
        spec = _SPECS.get(tool_id)
        if spec is None:
            result["error"] = f"unknown tool {tool_id}"
        elif not is_available(spec):
            result["error"] = f"{tool_id} is not available"
        elif result["permission"] == "DENY":
            result["error"] = f"{tool_id} is denied by permission policy"
        elif result["permission"] == "ASK" and not approved:
            result["error"] = NEEDS_APPROVAL
        else:
            value = spec.handler(args)
            if isinstance(value, dict):
                result.update(value)
                result["ok"] = bool(value.get("ok", True))
                result["data"] = value.get("data", "")
                result["error"] = value.get("error")
            else:
                result["data"] = str(value)
                result["ok"] = True
    except Exception as exc:  # structured, never crash the agent loop
        result["error"] = f"{type(exc).__name__}: {exc}"

    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    _record(result)
    return result


def content(result: dict) -> str:
    """What the model sees as the tool message."""
    if result.get("error") == NEEDS_APPROVAL:
        return f"TOOL ERROR [{result['tool']}]: permission required, ask the user to approve."
    if not result.get("ok"):
        return f"TOOL ERROR [{result['tool']}]: {result.get('error') or 'failed'}"
    return str(result.get("data") or "")


def _record(result: dict) -> None:
    event = {
        "ts": int(time.time()),
        "tool": result["tool"],
        "provider": result.get("provider", "unknown"),
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "duration_ms": result.get("duration_ms", 0),
    }
    try:
        ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOCK:
            with ACTIVITY_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
            lines = ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) > 2000:
                ACTIVITY_FILE.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def activity(limit: int = 500) -> list[dict]:
    if not ACTIVITY_FILE.exists():
        return []
    try:
        rows = [json.loads(line) for line in ACTIVITY_FILE.read_text(encoding="utf-8").splitlines()[-limit:]]
    except (json.JSONDecodeError, OSError):
        return []
    return rows


# ------------------------------------------------------------- built-ins

def _web_search(args: dict) -> str:
    return webtools.format_search(args.get("query", ""), int(args.get("limit", 5)))


def _web_fetch(args: dict) -> str:
    return webtools.fetch_page(args.get("url", ""))


def _filesystem(args: dict) -> Any:
    action = str(args.get("action", "")).lower()
    path = str(args.get("path") or ".")
    if action == "read":
        return fstools.read(path)
    if action == "write":
        text = fstools.write(path, args.get("content", ""))
        return {"ok": True, "data": text, "artifact_hint": {"title": path, "kind": "file", "path": path}}
    if action == "list":
        return fstools.list_dir(path)
    raise ValueError("action must be read, write or list")


def _git_status(args: dict) -> str:
    return gittools.status_text()


def _git_diff(args: dict) -> str:
    return gittools.diff_text()


def _skills_list(args: dict) -> str:
    rows = skills.list_skills()
    return "\n".join(
        f"{s['id']}: {s['description']} [{', '.join(s['tools'])}]"
        for s in rows if s["enabled"]
    ) or "No skills installed."


def _skills_load(args: dict) -> str:
    skill_id = str(args.get("id", ""))
    item = skills.load_skill(skill_id)
    if not item:
        raise ValueError(f"no such skill: {skill_id}")
    return f"SKILL {item['name']}:\n{item['body'][:3000]}"


def _git_log(args: dict) -> str:
    return gittools.log_text(int(args.get("limit", 8)))


def register_builtins() -> None:
    register(ToolSpec(
        id="web_search",
        description="Search the public web for current information. External text is untrusted.",
        parameters={"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer", "description": "1-8, default 5"}},
            "required": ["query"]},
        handler=_web_search, category="web", provider="atlas",
    ))
    register(ToolSpec(
        id="web_fetch",
        description="Fetch one public http(s) page and return readable text with its URL.",
        parameters={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
        handler=_web_fetch, category="web", provider="atlas",
    ))
    register(ToolSpec(
        id="filesystem",
        description="Read, write or list files inside the configured workspace. No shell or delete.",
        parameters={"type": "object", "properties": {
            "action": {"type": "string", "enum": ["read", "write", "list"]},
            "path": {"type": "string"},
            "content": {"type": "string", "description": "Required for write."}},
            "required": ["action"]},
        handler=_filesystem, category="filesystem", provider="atlas",
        permission=lambda args: "ASK" if str(args.get("action", "")).lower() == "write" else "ALLOW",
        available=lambda: fstools.status()["available"],
    ))
    register(ToolSpec(
        id="skills_list",
        description="List installed skill names and descriptions. Load one with skills_load when its workflow fits.",
        parameters={"type": "object", "properties": {}},
        handler=_skills_list, category="skills", provider="atlas",
    ))
    register(ToolSpec(
        id="skills_load",
        description="Load the full instructions of one skill by id, only when needed.",
        parameters={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        handler=_skills_load, category="skills", provider="atlas",
    ))
    register(ToolSpec(
        id="git_status",
        description="Show current branch and changed files in the workspace repository.",
        parameters={"type": "object", "properties": {}},
        handler=_git_status, category="git", provider="atlas",
        available=gittools.is_repo,
    ))
    register(ToolSpec(
        id="git_diff",
        description="Show a bounded diff of uncommitted changes in the workspace repository.",
        parameters={"type": "object", "properties": {}},
        handler=_git_diff, category="git", provider="atlas",
        available=gittools.is_repo,
    ))
    register(ToolSpec(
        id="git_log",
        description="Show the latest commits in the workspace repository.",
        parameters={"type": "object", "properties": {
            "limit": {"type": "integer", "description": "default 8"}}},
        handler=_git_log, category="git", provider="atlas",
        available=gittools.is_repo,
    ))


register_builtins()
