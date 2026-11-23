"""Bounded action planner for local models that will not emit tool calls.

Small reasoning models answer perfectly well in JSON mode but never produce
native tool calls. This module asks for a *plan* (not facts, not news) and the
harness executes only validated, workspace-confined actions. One plan per turn,
at most three actions — no autonomous loops.
"""

from __future__ import annotations

import json
import re

import registry
from llm import chat

SYSTEM = """You are the action planner for Atlas, a local coding agent.
Return JSON ONLY with this exact shape:
{"actions":[{"tool":"files","args":{"action":"write","path":"relative.py","content":"..."}}],"answer":"one-sentence summary"}

Allowed tools:
- files: action is list, read, write or mkdir; path is relative to the workspace.
- terminal: command is one short allowlisted read-only command.

Rules:
- At most 3 actions. Put the full file content in "content" for write.
- If the user asks to run/execute code, add a terminal action
  {"tool":"terminal","args":{"command":"uv run python <path>"}} after writing.
- Never use absolute paths or '..'. Never claim an action succeeded.
- For pure advice, explanation or web research, return actions: [] and answer.
- If no action is needed, actions: [] and a one-sentence answer.
"""

_INTENT = re.compile(
    r"\b(?:write|create|make|add|edit|change|fix|patch|implement|refactor|"
    r"build|generate|update|delete|remove)\b.*\b(?:file|script|code|function|"
    r"class|module|bug|test|app|tool|program|readme|\.py|\.js|\.md)\b"
    r"|\b(?:fix|debug|implement|refactor)\b",
    re.IGNORECASE,
)


REPORT_SYSTEM = (
    "You are reporting tool actions Atlas already executed. Use only the "
    "provided results. State what was done and the observed output in past "
    "tense, at most 3 sentences. Never give setup instructions, never describe "
    "completed work as future, never claim a tool that ran was unavailable."
)


def needs_actions(text: str) -> bool:
    return bool(_INTENT.search(str(text or "")))


def _validate(data: dict) -> tuple[list[dict], list[str]]:
    """Keep only safe, syntactically valid actions; report what was rejected."""
    actions: list[dict] = []
    errors: list[str] = []
    seen: set[str] = set()
    for item in (data.get("actions") or [])[:3]:
        if not isinstance(item, dict):
            continue
        tool = str(item.get("tool") or "").lower()
        args = item.get("args") or {}
        if tool not in ("files", "terminal") or not isinstance(args, dict):
            continue
        if tool == "files":
            action = str(args.get("action") or "").lower()
            path = str(args.get("path") or "")
            if action not in ("list", "read", "write", "mkdir"):
                continue
            if not path or path.startswith(("/", "~")) or ".." in path:
                continue
            content = str(args.get("content") or "")
            if len(content) > 50_000:
                continue
            if action == "write" and path.endswith(".py"):
                try:
                    compile(content, path, "exec")
                except SyntaxError as exc:
                    errors.append(f"{path}: {exc.msg} on line {exc.lineno}")
                    continue  # never write code that cannot even parse
        else:
            command = str(args.get("command") or "")
            if not command or any(ch in command for ch in (";", "&", "|", ">", "<", "`", "$(")):
                continue
        key = tool + ":" + json.dumps(args, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        actions.append({"tool": tool, "args": args})
    return actions, errors


def _ask(messages: list[dict], tier: str) -> dict:
    message = chat(
        messages, temperature=0, max_tokens=2048, tier=tier,
        response_format={"type": "json_object"},
    )
    data = json.loads(message.content or "{}")
    return data if isinstance(data, dict) else {}


def plan(text: str, tier: str = "local") -> dict:
    """Return {"actions": [...], "answer": "..."}. Never raises."""
    if not needs_actions(text):
        return {"actions": [], "answer": ""}
    try:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": str(text)},
        ]
        data = _ask(messages, tier)
        actions, errors = _validate(data)
        if errors:
            # One bounded repair: show the model the real SyntaxError.
            messages.append({"role": "assistant", "content": json.dumps(data)})
            messages.append({"role": "user", "content":
                "Your plan wrote invalid Python: " + "; ".join(errors) +
                ". Return corrected JSON ONLY."})
            fixed = _ask(messages, tier)
            fixed_actions, fixed_errors = _validate(fixed)
            if not fixed_errors:
                actions, data = fixed_actions, fixed
    except Exception:
        return {"actions": [], "answer": ""}
    return {"actions": actions, "answer": str(data.get("answer") or "")[:400]}


def execute(actions: list[dict]) -> list[dict]:
    """Run validated actions. Destructive/unapproved ones are skipped, not forced."""
    done: list[dict] = []
    for index, action in enumerate(actions):
        name, args = action["tool"], action["args"]
        if registry.permission(name, args) == "ASK":
            done.append({"id": f"plan_{index}", "name": name, "args": args,
                         "text": "Permission required; action skipped.", "ok": False})
            continue
        result = registry.run(name, args, approved=True)
        done.append({"id": f"plan_{index}", "name": name, "args": args,
                     "text": registry.content(result), "ok": bool(result.get("ok"))})
    return done
