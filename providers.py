"""Named model providers — local runtimes and hosted APIs in one registry.

Atlas already speaks OpenAI-style chat completions, so every preset below
works without a new SDK. A preset records three things that matter to users:

  * where the request goes (base URL / local flag),
  * which environment variable holds the key (never written into source),
  * what Atlas sends there (prompt, tool schemas, tool results).

The local entries need no account. The hosted entries are listed in the order
that is usually easiest to connect: one key, generous free tier, then cheap
paid options. Nothing here is enabled by default.
"""

from __future__ import annotations

import os

from config import ROOT_DATA  # noqa: F401  (kept for a stable import surface)

# ease: lower is easier to connect for a new user.
PRESETS: dict[str, dict] = {
    "ollama": {
        "name": "Ollama", "local": True, "ease": -1,
        "base_url": "http://127.0.0.1:11434/v1", "key_env": "",
        "install": "ollama pull qwen2.5:3b",
        "egress": "nothing leaves this machine",
    },
    "lmstudio": {
        "name": "LM Studio", "local": True, "ease": 0,
        "base_url": "http://127.0.0.1:1234/v1", "key_env": "",
        "install": "download a model, then start the local server",
        "egress": "nothing leaves this machine",
    },
    "llamacpp": {
        "name": "llama.cpp", "local": True, "ease": 0,
        "base_url": "http://127.0.0.1:8080/v1", "key_env": "",
        "install": "llama-server -m model.gguf",
        "egress": "nothing leaves this machine",
    },
    "vllm": {
        "name": "vLLM", "local": True, "ease": 0,
        "base_url": "http://127.0.0.1:8000/v1", "key_env": "",
        "install": "start vLLM with your model",
        "egress": "nothing leaves this machine (unless you bind it to a LAN address)",
    },
    "openrouter": {
        "name": "OpenRouter", "local": False, "ease": 1,
        "base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY",
        "install": "one key for hundreds of models: https://openrouter.ai/keys",
        "egress": "prompts, tool schemas and tool results go to OpenRouter and the chosen upstream model",
    },
    "groq": {
        "name": "Groq", "local": False, "ease": 2,
        "base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY",
        "install": "free key: https://console.groq.com/keys",
        "egress": "prompts and tool schemas/results go to Groq; very fast inference",
    },
    "gemini": {
        "name": "Google Gemini", "local": False, "ease": 3,
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GEMINI_API_KEY",
        "install": "free key: https://aistudio.google.com/apikey",
        "egress": "prompts and tool schemas/results go to Google",
    },
    "deepseek": {
        "name": "DeepSeek", "local": False, "ease": 4,
        "base_url": "https://api.deepseek.com/v1", "key_env": "DEEPSEEK_API_KEY",
        "install": "cheap key: https://platform.deepseek.com/api_keys",
        "egress": "prompts and tool schemas/results go to DeepSeek",
    },
    "together": {
        "name": "Together AI", "local": False, "ease": 5,
        "base_url": "https://api.together.xyz/v1", "key_env": "TOGETHER_API_KEY",
        "install": "key: https://api.together.ai/settings/api-keys",
        "egress": "prompts and tool schemas/results go to Together AI",
    },
    "mistral": {
        "name": "Mistral", "local": False, "ease": 6,
        "base_url": "https://api.mistral.ai/v1", "key_env": "MISTRAL_API_KEY",
        "install": "key: https://console.mistral.ai/api-keys/",
        "egress": "prompts and tool schemas/results go to Mistral",
    },
    "openai": {
        "name": "OpenAI", "local": False, "ease": 7,
        "base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
        "install": "key: https://platform.openai.com/api-keys",
        "egress": "prompts and tool schemas/results go to OpenAI",
    },
}


def get(name: str) -> dict | None:
    key = str(name or "").strip().lower().replace(" ", "").replace("_", "")
    return PRESETS.get(key)


def api_key(preset: dict) -> str:
    variable = preset.get("key_env") or ""
    return os.getenv(variable, "").strip() if variable else "ollama"


def list_presets() -> list[dict]:
    rows = []
    for key, preset in PRESETS.items():
        row = dict(preset, id=key)
        row["has_key"] = bool(api_key(preset)) if not preset["local"] else True
        rows.append(row)
    return sorted(rows, key=lambda row: (row["ease"], row["name"]))


def is_local(base_url: str) -> bool:
    value = str(base_url or "").lower()
    return any(host in value for host in ("127.0.0.1", "localhost", "0.0.0.0", "::1"))


def for_base_url(base_url: str) -> dict | None:
    target = str(base_url or "").rstrip("/")
    for key, preset in PRESETS.items():
        if preset["base_url"].rstrip("/") == target:
            return dict(preset, id=key)
    return None
