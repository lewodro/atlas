"""Local model writes the spec, frontier model writes the code.

The local model is cheap and private: it turns a loose request into a compact
implementation brief. The configured frontier API then returns a structured
file set. The harness — not the model — writes the files, checks Python syntax
and optionally runs the script inside the workspace.

Every stage is labelled, and the frontier call is recorded in the egress
ledger like any other outbound API call.
"""

from __future__ import annotations

import json
import re

import config
import fstools
import llm
import termtools

SPEC_SYSTEM = """Return JSON ONLY:
{"goal":"concrete deliverable","language":"python|js|md|other",
 "files":["relative/path.ext"],"constraints":["short bullets"],
 "verify":"what command or check proves it works"}
No code here. Max 12 words per item."""

CODE_SYSTEM = """Write the implementation now. Return JSON ONLY:
{"files":[{"path":"relative/path.ext","content":"complete file text"}],
 "notes":"short explanation"}
Rules:
- Only relative paths inside the workspace. No absolute paths or '..'.
- Complete file contents, not snippets or placeholders.
- Only create the files in the brief unless a rename is explained.
- No secrets, credentials or network calls unless requested.
- Never claim a test ran; the harness does that."""


def _spec(request: str, model: str | None) -> dict:
    try:
        reply = llm.chat(
            [{"role": "system", "content": SPEC_SYSTEM},
             {"role": "user", "content": request}],
            None, tier="local", model=model, temperature=0, timeout=25,
            max_tokens=350, response_format={"type": "json_object"},
        )
        data = json.loads(reply.content or "{}")
        if isinstance(data, dict) and data.get("goal"):
            return data
    except Exception:
        pass
    return {"goal": request[:300], "language": "python",
            "files": [], "constraints": [], "verify": "check the written files"}


def _safe_files(payload: dict) -> list[dict]:
    rows = []
    for item in (payload.get("files") or [])[:8]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        content = str(item.get("content") or "")
        if not path or path.startswith(("/", "~")) or ".." in path:
            continue
        if len(content.encode("utf-8")) > 200_000:
            continue
        rows.append({"path": path, "content": content})
    return rows


def run(request: str, *, model: str | None = None, execute: bool = True) -> dict:
    request = str(request or "").strip()
    if not request:
        raise ValueError("request is empty")
    if not config.FRONTIER_READY:
        return {
            "ok": False,
            "error": ("frontier tier is not configured. Set ATLAS_FRONTIER_BASE_URL, "
                      "ATLAS_FRONTIER_API_KEY and ATLAS_FRONTIER_MODEL in .env."),
            "request": request,
        }
    brief = _spec(request, model)
    try:
        reply = llm.chat(
            [{"role": "system", "content": CODE_SYSTEM},
             {"role": "user", "content": json.dumps(brief, ensure_ascii=False)[:2500]}],
            None, tier="frontier", temperature=0.2, timeout=60, max_tokens=3000,
            response_format={"type": "json_object"},
        )
        payload = json.loads((reply.content or "{}"))
        if not isinstance(payload, dict):
            raise ValueError("frontier returned a non-object JSON payload")
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "request": request, "brief": brief}

    written, rejected, checks = [], [], []
    for item in _safe_files(payload):
        path = item["path"]
        content = item["content"]
        if path.endswith(".py"):
            try:
                compile(content, path, "exec")
            except SyntaxError as exc:
                rejected.append({"path": path, "error": f"line {exc.lineno}: {exc.msg}"})
                continue
        try:
            written.append({"path": path, "result": fstools.write(path, content)})
        except Exception as exc:
            rejected.append({"path": path, "error": str(exc)})
    for item in payload.get("files", [])[len(_safe_files(payload)):]:
        rejected.append({"path": str(item.get("path", "?")),
                         "error": "unsafe path or oversized content"})

    if execute and written:
        for item in written[:3]:
            if not item["path"].endswith(".py"):
                continue
            try:
                item["run"] = termtools.run(f"python {item['path']}")[:1000]
                checks.append(f"{item['path']}: {item['run'][:200]}")
            except Exception as exc:
                item["run_error"] = str(exc)
                checks.append(f"{item['path']}: failed - {exc}")

    return {
        "ok": bool(written),  # rejected items are reported, not fatal
        "request": request,
        "brief": brief,
        "files": written,
        "rejected": rejected,
        "checks": checks,
        "notes": str(payload.get("notes") or "")[:800],
        "local_model": model or config.MODEL,
        "frontier_model": config.FRONTIER_MODEL,
        "frontier_endpoint": config.FRONTIER_BASE_URL,
    }
