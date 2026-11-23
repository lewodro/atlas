"""Which model answers — and where it lives.

Atlas talks to anything that speaks the OpenAI chat-completions API:

    Ollama            http://127.0.0.1:11434/v1     (default)
    LM Studio         http://127.0.0.1:1234/v1
    llama.cpp server  http://127.0.0.1:8080/v1
    vLLM              http://127.0.0.1:8000/v1
    OpenRouter        https://openrouter.ai/api/v1
    OpenAI            https://api.openai.com/v1
    your LAN box      http://your-gpu-host:11434/v1

Runtime choices live in data/settings.json (gitignored, next to the database)
and win over .env, so the GUI can switch models without a restart:

    atlas models                       # what is installed / reachable
    atlas models --use qwen2.5:7b      # make it the default
    atlas models --endpoint http://127.0.0.1:1234/v1 --use qwen2.5-7b-instruct
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import config

SETTINGS = config.ROOT_DATA / "settings.json"
FIELDS = ("base_url", "api_key", "model")

DEFAULTS = {
    "base_url": config.BASE_URL,
    "api_key": config.API_KEY,
    "model": config.MODEL,
}

#: Local runtimes and their default OpenAI-compatible ports. Derived from the
#: one provider registry in config.py, so CLI, GUI and doctor agree. Probed in
#: parallel, so opening the GUI costs about one second even if none are up.
RUNTIMES = [(p["name"], p["base_url"]) for p in config.PROVIDERS.values()]

_AUTO: dict | None = None


def _auto_pick() -> dict:
    """First local runtime that answers, with its first chat model."""
    for runtime in scan_runtimes():
        if runtime["models"]:
            return {
                "base_url": runtime["base_url"],
                # Non-empty: openai >= 3.42 rejects an empty key.
                "api_key": config.API_KEY,
                "model": runtime["models"][0],
            }
    return {}


def load() -> dict:
    """Saved settings over defaults. Missing or broken file = defaults."""
    data = dict(DEFAULTS)
    if not SETTINGS.exists() and not os.getenv("ATLAS_MODEL") and not os.getenv("ATLAS_BASE_URL"):
        global _AUTO
        if _AUTO is None:
            _AUTO = {}  # guard against re-entry while probing
            _AUTO = _auto_pick()
        data.update(_AUTO)
    if SETTINGS.exists():
        try:
            saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            saved = {}
        for key in FIELDS:
            value = str(saved.get(key) or "").strip()
            if value:
                data[key] = value
    return data


def save(**patch: str) -> dict:
    """Persist a partial change. Empty strings mean 'leave it alone'."""
    data = load()
    for key in FIELDS:
        if key in patch:
            value = str(patch[key]).strip()
            if value:
                data[key] = value
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _get(url: str, api_key: str, timeout: float = 4.0):
    key = api_key or config.API_KEY
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def native_status(provider: str, timeout: float = 1.5) -> dict | None:
    """Cheap native status probe (Ollama /api/tags, others /v1/models).

    Returns the decoded payload, or None when the runtime is offline. Used by
    the doctor so it can distinguish 'server down' from 'model not installed'.
    """
    preset = config.PROVIDERS.get(provider)
    if not preset:
        return None
    url = preset["native_url"].rstrip("/") + preset["probe"]
    try:
        return _get(url, preset["api_key"], timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def list_models(
    base_url: str | None = None, api_key: str | None = None, timeout: float = 4.0
) -> list[str]:
    """Model ids from any OpenAI-compatible endpoint. Never raises."""
    if base_url is not None and api_key is not None:
        base, key = base_url.rstrip("/"), api_key
    else:
        current = load()
        base = (base_url or current["base_url"]).rstrip("/")
        key = api_key if api_key is not None else current["api_key"]
    try:
        payload = _get(f"{base}/models", key, timeout=timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    ids = {
        str(m.get("id")) for m in items
        if isinstance(m, dict) and m.get("id") and "embed" not in str(m["id"]).lower()
    }

    def rank(name: str):
        name = name.lower()
        score = 0
        if name.startswith(("qwen", "llama", "gemma", "mistral", "deepseek", "phi")):
            score += 3
        if "abliterated" in name or "test" in name:
            score -= 3
        if name.endswith(":latest"):
            score -= 1
        return (-score, name)

    return sorted(ids, key=rank)


def scan_runtimes(timeout: float = 1.2) -> list[dict]:
    """Probe the usual local ports in parallel: Ollama, LM Studio, etc."""
    def probe(item: tuple[str, str]) -> dict:
        name, base = item
        return {
            "name": name,
            "base_url": base,
            "models": list_models(base, "", timeout=timeout),
        }

    with ThreadPoolExecutor(max_workers=len(RUNTIMES)) as pool:
        found = list(pool.map(probe, RUNTIMES))
    current = load()["base_url"]
    for runtime in found:
        runtime["ok"] = bool(runtime["models"])
        runtime["active"] = runtime["base_url"].rstrip("/") == current.rstrip("/")
    return found


def _ollama_root(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def pull(model: str, base_url: str | None = None):
    """Download a model from the Ollama registry, yielding progress events.

    Only Ollama implements /api/pull. LM Studio, vLLM and hosted APIs will
    fail here — install the model their way instead.
    """
    base = _ollama_root(base_url or load()["base_url"])
    request = urllib.request.Request(
        f"{base}/api/pull",
        data=json.dumps({"model": model, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=900) as response:
        for line in response:
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def reachable(base_url: str | None = None, api_key: str | None = None) -> bool:
    return bool(list_models(base_url, api_key))


def describe() -> dict:
    """Everything the GUI needs to render the model picker."""
    current = load()
    models = [
        name for name in list_models(current["base_url"], current["api_key"])
        if "embed" not in name.lower()
    ]
    return {
        "base_url": current["base_url"],
        "provider": config.provider_for_base_url(current["base_url"]) or "custom",
        "model": current["model"],
        "models": models,
        "reachable": bool(models),
        "remote": config.REMOTE,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="list and choose the model atlas talks to")
    parser.add_argument("--endpoint", help="OpenAI-compatible base URL, e.g. http://127.0.0.1:1234/v1")
    parser.add_argument("--api-key", dest="api_key", help="key for that endpoint (local ones ignore it)")
    parser.add_argument("--use", help="make this model id the default")
    parser.add_argument("--runtime", help="use a detected runtime: ollama|lmstudio|llamacpp|vllm")
    parser.add_argument("--pull", metavar="MODEL", help="download it with Ollama, then use it")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if args.runtime:
        match = next((r for r in RUNTIMES if args.runtime.lower() in r[0].lower().replace(" ", "")), None)
        if not match:
            raise SystemExit(f"unknown runtime {args.runtime!r}; try: " + ", ".join(
                name.lower().replace(" ", "") for name, _ in RUNTIMES
            ))
        args.endpoint = match[1]

    if args.pull:
        last = ""
        try:
            for event in pull(args.pull, args.endpoint):
                status = event.get("status", "")
                total, done = event.get("total") or 0, event.get("completed") or 0
                line = f"{status} {100 * done // total}%" if total else status
                if line != last:
                    print(f"  {line}")
                    last = line
        except Exception as exc:
            raise SystemExit(f"pull failed: {exc}")
        args.use = args.use or args.pull

    if args.endpoint or args.api_key or args.use:
        save(**{k: v for k, v in vars(args).items() if k in FIELDS and v})
        print(f"endpoint: {load()['base_url']}")
        print(f"model:    {load()['model']}")

    info = describe()
    if args.json:
        print(json.dumps({**info, "runtimes": scan_runtimes()}, indent=2))
        return

    print("\ndetected")
    for runtime in scan_runtimes():
        mark = "*" if runtime["active"] else " "
        status = ", ".join(runtime["models"][:3]) if runtime["ok"] else "offline"
        print(f"  {mark} {runtime['name']:10} {runtime['base_url']:30} {status}")

    print(f"\n{info['base_url']}")
    if not info["models"]:
        print("  no models found — is the server running?")
        return
    for name in info["models"]:
        print(f"  {'*' if name == info['model'] else ' '} {name}")


if __name__ == "__main__":
    main()
