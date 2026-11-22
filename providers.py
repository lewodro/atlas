"""External tool providers (lightweight MCP-style bridge).

A provider is a local HTTP service with an `/invoke` endpoint. Its manifest
lists tool ids and JSON schemas. Registered tools become normal registry tools
and appear in the model, CLI, API and GUI — no core-loop changes required.

    atlas providers register local-tools ./provider.json
    atlas providers list
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import config
import netguard

FILE = config.ROOT_DATA / "providers.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")


def _load() -> list[dict]:
    if FILE.exists():
        try:
            value = json.loads(FILE.read_text())
            return value if isinstance(value, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(rows: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(rows, indent=2) + "\n")


def list_providers() -> list[dict]:
    return _load()


def register(provider_id: str, name: str, base_url: str, tools: list[dict]) -> dict:
    if not SAFE_ID.match(provider_id):
        raise ValueError("invalid provider id")
    base_url = str(base_url or "").strip().rstrip("/")
    netguard.vetted_target(base_url + "/invoke")  # SSRF check at registration
    if not isinstance(tools, list) or not tools:
        raise ValueError("provider needs at least one tool")
    cleaned = []
    for tool in tools:
        tid = str(tool.get("id") or "")
        if not SAFE_ID.match(tid):
            raise ValueError(f"invalid tool id: {tid}")
        cleaned.append({
            "id": tid,
            "description": str(tool.get("description") or tid)[:240],
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        })
    row = {"id": provider_id, "name": name or provider_id,
           "base_url": base_url, "tools": cleaned}
    rows = _load()
    rows = [item for item in rows if item.get("id") != provider_id]
    rows.append(row)
    _save(rows)
    return row


def remove(provider_id: str) -> bool:
    rows = _load()
    kept = [row for row in rows if row.get("id") != provider_id]
    if len(kept) == len(rows):
        return False
    _save(kept)
    return True


def invoke(provider: dict, tool_id: str, arguments: dict) -> str:
    url = provider["base_url"] + "/invoke"
    netguard.vetted_target(url)
    payload = json.dumps({"tool": tool_id, "arguments": arguments}).encode()
    request = urllib.request.Request(
        url, data=payload, headers={
            "Content-Type": "application/json",
            "User-Agent": "AtlasProvider/1.0",
            "X-Atlas-Provider": str(provider.get("id", "")),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(20000).decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"provider request failed: {type(exc).__name__}") from exc
    try:
        value = json.loads(data)
        if isinstance(value, dict) and "result" in value:
            return str(value["result"])
    except json.JSONDecodeError:
        pass
    return data[:8000]


def build_specs(ToolSpec):
    """Return registry ToolSpecs for all registered provider tools."""
    specs = []
    for provider in _load():
        for tool in provider.get("tools", []):
            def handler(args, provider=provider, tool_id=tool["id"]):
                return invoke(provider, tool_id, args or {})
            specs.append(ToolSpec(
                id=f"{provider['id']}_{tool['id']}",
                description=f"[{provider['name']}] {tool['description']}",
                parameters=tool.get("parameters") or {"type": "object", "properties": {}},
                handler=handler,
                category="provider",
                permission="ASK",
                provider=provider["id"],
            ))
    return specs


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="register external tool providers")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    reg = sub.add_parser("register")
    reg.add_argument("id")
    reg.add_argument("manifest", help="JSON file with name, base_url and tools")
    rem = sub.add_parser("remove")
    rem.add_argument("id")
    args = parser.parse_args()

    if args.action == "list":
        for row in list_providers():
            print(f"{row['id']:18} {row['base_url']:32} {len(row['tools'])} tools")
        if not list_providers():
            print("no providers registered")
    elif args.action == "register":
        data = json.loads(Path(args.manifest).read_text())
        row = register(args.id, data.get("name", ""), data.get("base_url", ""),
                       data.get("tools", []))
        print(f"registered {row['id']} with {len(row['tools'])} tools")
    elif args.action == "remove":
        print("removed" if remove(args.id) else "no such provider")


if __name__ == "__main__":
    main()
