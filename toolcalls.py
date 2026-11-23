"""Small-model tool-call repair.

Valid native tool calls are preferred. When a local model leaks a call into
prose (or emits slightly malformed JSON), recover it here and feed the tool
result back into the loop — do not just print it and answer from memory.

Bounded: this parses text only; it never invents a tool call or loops by itself.
"""

from __future__ import annotations

import ast
import json
import re

_FENCE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)


def _loads(raw: str):
    """Parse a JSON object, tolerating fences, trailing commas and single quotes."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = _FENCE.sub("", text, count=1)
    text = text.split("```", 1)[0].strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        value = ast.literal_eval(text)
        return value if isinstance(value, dict) else None
    except (ValueError, SyntaxError, TypeError):
        return None


def _objects(text: str) -> list[tuple[int, int]]:
    """Spans of balanced {...} blocks, ignoring braces inside strings."""
    spans: list[tuple[int, int]] = []
    start = -1
    depth = 0
    quoted = False
    escaped = False
    for i, char in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append((start, i + 1))
                start = -1
    return spans


def _call(data) -> dict | None:
    if not isinstance(data, dict) or not data.get("name"):
        return None
    args = data.get("arguments") or {}
    if isinstance(args, str):
        args = _loads(args) or {}
    if not isinstance(args, dict):
        args = {}
    return {"name": str(data["name"]), "arguments": args}


def extract(text: str) -> tuple[list[dict], str]:
    """Return (calls, clean_text). The caller executes calls and continues."""
    source = str(text or "")
    calls: list[dict] = []
    spans: list[tuple[int, int]] = []

    for start, end in _objects(source):
        call = _call(_loads(source[start:end]))
        if call:
            calls.append(call)
            spans.append((start, end))

    # An unterminated <tool_call> ... JSON tail is common on small models.
    tag = source.find("<tool_call>")
    if tag >= 0 and not any(start <= tag for start, _ in spans):
        tail = source[tag + len("<tool_call>"):].strip()
        parsed = _loads(tail)
        if parsed is None:
            parsed = _loads(tail + "}") or _loads(tail + "}}")
        call = _call(parsed)
        if call:
            calls.append(call)
            spans.append((tag, len(source)))
        else:
            spans.append((tag, len(source)))  # drop half-written call text

    chunks = []
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor:
            chunks.append(source[cursor:start])
        cursor = max(cursor, end)
    chunks.append(source[cursor:])
    clean = re.sub(r"\s+", " ", " ".join(chunks)).replace("<tool_call>", "").strip()
    return calls, clean
