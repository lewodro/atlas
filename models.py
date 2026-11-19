"""Which model answers — and where it lives.

Atlas talks to anything that speaks the OpenAI chat-completions API:

    Ollama            http://127.0.0.1:11434/v1     (default)
    LM Studio         http://127.0.0.1:1234/v1
    llama.cpp server  http://127.0.0.1:8080/v1
    vLLM              http://127.0.0.1:8000/v1
    OpenRouter        https://openrouter.ai/api/v1
    OpenAI            https://api.openai.com/v1
    your LAN box      http://192.168.1.42:11434/v1

Runtime choices live in data/settings.json (gitignored, next to the database)
and win over .env, so the GUI can switch models without a restart:

    atlas models                       # what is installed / reachable
    atlas models --use qwen2.5:7b      # make it the default
    atlas models --endpoint http://127.0.0.1:1234/v1 --use qwen2.5-7b-instruct
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import config

SETTINGS = config.ROOT_DATA / "settings.json"
FIELDS = ("base_url", "api_key", "model")

DEFAULTS = {
    "base_url": config.BASE_URL,
    "api_key": config.API_KEY,
    "model": config.MODEL,
}


def load() -> dict:
    """Saved settings over defaults. Missing or broken file = defaults."""
    data = dict(DEFAULTS)
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
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def list_models(base_url: str | None = None, api_key: str | None = None) -> list[str]:
    """Model ids from any OpenAI-compatible endpoint. Never raises."""
    current = load()
    base = (base_url or current["base_url"]).rstrip("/")
    key = api_key or current["api_key"]
    try:
        payload = _get(f"{base}/models", key)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return []
    return sorted({str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")})


def reachable(base_url: str | None = None, api_key: str | None = None) -> bool:
    return bool(list_models(base_url, api_key))


def describe() -> dict:
    """Everything the GUI needs to render the model picker."""
    current = load()
    models = list_models(current["base_url"], current["api_key"])
    return {
        "base_url": current["base_url"],
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
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if args.endpoint or args.api_key or args.use:
        save(**{k: v for k, v in vars(args).items() if k in FIELDS and v})
        print(f"endpoint: {load()['base_url']}")
        print(f"model:    {load()['model']}")

    info = describe()
    if args.json:
        print(json.dumps(info, indent=2))
        return

    print(f"\n{info['base_url']}")
    if not info["models"]:
        print("  no models found — is the server running?")
        return
    for name in info["models"]:
        print(f"  {'*' if name == info['model'] else ' '} {name}")


if __name__ == "__main__":
    main()
