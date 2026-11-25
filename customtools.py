"""User-defined tools, loaded from data/custom_tools.json.

A custom tool is a small JSON record in your own gitignored data folder. It is
registered through the same registry as built-in tools, so permissions, the
CLI, the API and the GUI all see it automatically.

Supported kinds:
  echo     - returns its arguments (safe way to test a schema)
  command  - runs a fixed allowlisted read-only command with {arg} placeholders
  http     - GETs a fixed public URL with query parameters (SSRF-checked)

No arbitrary shell and no arbitrary URL: both are fixed by the user's JSON
file and re-checked at call time.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess

import config
import egress
import netguard
import registry

FILE = config.ROOT_DATA / "custom_tools.json"
SAFE_COMMANDS = {"git", "ls", "pwd", "cat", "tree", "echo"}
_PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_registered: set[str] = set()


def load() -> list[dict]:
    if not FILE.exists():
        return []
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def validate(spec: dict) -> str:
    """Return an error string, or '' when the tool is safe to register."""
    name = str(spec.get("name") or "").strip()
    kind = str(spec.get("kind") or "").strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_]{2,30}", name):
        return "name must be 3-30 lowercase letters/digits/underscore"
    existing = registry.get(name)
    if existing and existing.provider != "user":
        return f"name {name!r} conflicts with a built-in tool"
    if kind not in ("echo", "command", "http"):
        return "kind must be echo, command or http"
    if kind == "command":
        command = str(spec.get("command") or "")
        parts = shlex.split(command)
        if not parts or parts[0] not in SAFE_COMMANDS:
            return f"command must start with one of {sorted(SAFE_COMMANDS)}"
        if any(ch in command for ch in (";", "&", "|", ">", "<", "`", "$(")):
            return "shell chaining is not allowed"
    if kind == "http":
        url = str(spec.get("url") or "")
        if not url.startswith(("https://", "http://")):
            return "http tools need an absolute http(s) URL"
        try:
            netguard.vetted_target(url)
        except netguard.NetError as exc:
            return f"unsafe URL: {exc}"
    return ""


def _handler(spec: dict):
    kind = str(spec.get("kind") or "").lower()
    name = str(spec.get("name") or "")

    if kind == "echo":
        def echo(args: dict) -> str:
            return json.dumps({"tool": name, "args": args or {}}, ensure_ascii=False)
        return echo

    if kind == "command":
        import fstools

        template = str(spec.get("command") or "")

        def command(args: dict) -> str:
            values = {
                key: re.sub(r"[^\w./-]", "", str(value))
                for key, value in (args or {}).items()
            }
            parts = [_PLACEHOLDER.sub(
                lambda match: values.get(match.group(1), ""), token
            ) for token in shlex.split(template)]
            if not parts or parts[0] not in SAFE_COMMANDS:
                raise ValueError("command failed safety check")
            done = subprocess.run(
                parts, cwd=fstools.workspace(), capture_output=True, text=True,
                timeout=20,
            )
            output = (done.stdout or done.stderr or "").strip()
            return output[:4000] or f"({name} returned no output)"
        return command

    url = str(spec.get("url") or "")
    params = spec.get("params") or {}

    def http(args: dict) -> str:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        supplied = {key: str(value) for key, value in (args or {}).items()
                    if key in params}
        pairs = [(str(key), str(value)) for key, value in params.items()
                 if key in supplied or not str(value).startswith("{")]
        pairs += list(supplied.items())
        parsed = urlparse(url)
        target = urlunparse(parsed._replace(query=urlencode(pairs)))
        egress.record([{"role": "user", "content": json.dumps(supplied)}],
                      None, target, f"custom:{name}")
        response = netguard.fetch(target)
        return response.text[:4000]
    return http


def register_all() -> int:
    count = 0
    for spec in load():
        name = str(spec.get("name") or "")
        if not name or name in _registered or validate(spec):
            continue
        parameters = {"type": "object", "properties": {}, "required": []}
        for key, value in (spec.get("args") or {}).items():
            if isinstance(value, dict):
                parameters["properties"][str(key)] = value
        for key in (spec.get("required") or []):
            if str(key) in parameters["properties"]:
                parameters["required"].append(str(key))
        registry.register(registry.ToolSpec(
            id=name,
            description=str(spec.get("description") or f"Custom {spec.get('kind')} tool")[:400],
            parameters=parameters,
            handler=_handler(spec),
            category="custom",
            permission="ASK" if spec.get("kind") == "http" else "ALLOW",
            provider="user",
        ))
        _registered.add(name)
        count += 1
    return count


def example() -> dict:
    return {
        "name": "echo_args",
        "kind": "echo",
        "description": "Return the arguments I pass (safe custom-tool test)",
        "args": {"text": {"type": "string", "description": "anything"}},
        "required": ["text"],
    }


def create_example() -> str:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    if not FILE.exists():
        FILE.write_text(json.dumps([example()], indent=2) + "\n", encoding="utf-8")
    return str(FILE)
