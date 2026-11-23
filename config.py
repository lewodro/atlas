"""Settings. Read once, from .env or the environment.

Everything that differs between machines is one line in .env:

    ATLAS_MODEL_PROVIDER=ollama
    ATLAS_MODEL=deepseek-r1:7b

The legacy ATLAS_BASE_URL / ATLAS_API_KEY names still work and take precedence
over the provider presets. `PROVIDERS` below is the single registry shared by
the CLI, the Web UI and the doctor (check.py).
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Tiny .env reader, so you don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()


def _clean(value: str | None, default: str = "") -> str:
    return str(value or default).strip()


def _root(url: str) -> str:
    """Native server root: http://host:11434/v1 -> http://host:11434."""
    url = url.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def _openai_url(url: str) -> str:
    """OpenAI-compatible base: http://host:11434 -> http://host:11434/v1."""
    url = _root(url)
    return f"{url}/v1"


def _normalise_provider(raw: str) -> str:
    key = _clean(raw, "ollama").lower().replace(" ", "").replace("_", "")
    return {"lmstudio": "lmstudio", "llamacpp": "llamacpp", "vllm": "vllm"}.get(
        key, key
    )


#: Local runtimes, one registry for config, CLI, GUI and doctor.
#: `probe` is a cheap native status path; `models` is the OpenAI list path.
PROVIDERS: dict[str, dict] = {
    "ollama": {
        "name": "Ollama",
        "url_env": "ATLAS_OLLAMA_URL",
        "native_url": _root(_clean(os.getenv("ATLAS_OLLAMA_URL"), "http://127.0.0.1:11434")),
        "base_url": _openai_url(_clean(os.getenv("ATLAS_OLLAMA_URL"), "http://127.0.0.1:11434")),
        "api_key": _clean(os.getenv("ATLAS_API_KEY"), "ollama"),
        "port": 11434,
        "probe": "/api/tags",
        "install": "ollama pull <model>",
    },
    "lmstudio": {
        "name": "LM Studio",
        "url_env": "ATLAS_LM_STUDIO_URL",
        "native_url": _root(_clean(os.getenv("ATLAS_LM_STUDIO_URL"), "http://127.0.0.1:1234")),
        "base_url": _openai_url(_clean(os.getenv("ATLAS_LM_STUDIO_URL"), "http://127.0.0.1:1234")),
        "api_key": _clean(os.getenv("ATLAS_API_KEY"), "lmstudio"),
        "port": 1234,
        "probe": "/v1/models",
        "install": "download a model in LM Studio, then start its local server",
    },
    "llamacpp": {
        "name": "llama.cpp",
        "url_env": "ATLAS_LLAMACPP_URL",
        "native_url": _root(_clean(os.getenv("ATLAS_LLAMACPP_URL"), "http://127.0.0.1:8080")),
        "base_url": _openai_url(_clean(os.getenv("ATLAS_LLAMACPP_URL"), "http://127.0.0.1:8080")),
        "api_key": _clean(os.getenv("ATLAS_API_KEY"), "llamacpp"),
        "port": 8080,
        "probe": "/v1/models",
        "install": "start llama-server with your GGUF model",
    },
    "vllm": {
        "name": "vLLM",
        "url_env": "ATLAS_VLLM_URL",
        "native_url": _root(_clean(os.getenv("ATLAS_VLLM_URL"), "http://127.0.0.1:8000")),
        "base_url": _openai_url(_clean(os.getenv("ATLAS_VLLM_URL"), "http://127.0.0.1:8000")),
        "api_key": _clean(os.getenv("ATLAS_API_KEY"), "vllm"),
        "port": 8000,
        "probe": "/v1/models",
        "install": "start vLLM with your model",
    },
}

#: ATLAS_BASE_URL (the original setting) always wins over a provider preset.
PROVIDER = _normalise_provider(os.getenv("ATLAS_MODEL_PROVIDER", "ollama"))
_PROVIDER = PROVIDERS.get(PROVIDER, PROVIDERS["ollama"])
BASE_URL = _clean(os.getenv("ATLAS_BASE_URL")) or _PROVIDER["base_url"]

#: The OpenAI SDK >= 3.42 refuses an empty key. Local servers ignore it; any
#: non-empty placeholder works. Never a secret for Ollama / LM Studio.
API_KEY = _clean(os.getenv("ATLAS_API_KEY")) or _PROVIDER["api_key"] or "ollama"

#: True when the model lives on another machine.
REMOTE = not any(h in BASE_URL for h in ("127.0.0.1", "localhost", "0.0.0.0"))

#: A 3B model fits in 8 GB of unified memory; a 7B does not.
MODEL = os.getenv("ATLAS_MODEL") or (
    "qwen2.5:7b" if REMOTE else "qwen2.5:3b"
)

# Keep local answers bounded. Long generations are the easiest way to make a
# small model feel slow; users can raise this for larger/custom models.
MAX_TOKENS = max(64, int(os.getenv("ATLAS_MAX_TOKENS", "1024")))

#: Reasoning models (DeepSeek R1, QwQ, o-series, "thinking" checkpoints) need a
#: much larger budget — they spend most of it thinking before any visible text.
#: Override either knob in .env; Atlas never generates without a ceiling.
REASONING_TOKENS = max(MAX_TOKENS, int(os.getenv("ATLAS_REASONING_TOKENS", "4096")))
REASONING_HINTS = ("r1", "qwq", "think", "o1", "o3", "phi-4-reasoning")

WHERE = f"{'remote GPU' if REMOTE else 'this machine'} @ {BASE_URL}"

# Native Ollama root (no /v1) — used for /api/tags, /api/pull and `ollama list`.
OLLAMA_URL = PROVIDERS["ollama"]["native_url"]

# Memory can live in the repo, any ordinary folder, or inside an Obsidian
# vault. ATLAS_NOTES_DIR is the precise override; ATLAS_VAULT chooses the
# conventional <vault>/Atlas/Memory folder.
_vault = os.getenv("ATLAS_VAULT", "").strip()
_notes = os.getenv("ATLAS_NOTES_DIR", "").strip()
ROOT_NOTES = Path(_notes).expanduser() if _notes else (
    Path(_vault).expanduser() / "Atlas" / "Memory" if _vault else ROOT / "notes"
)
ROOT_DATA = Path(os.getenv("ATLAS_DATA_DIR", str(ROOT / "data"))).expanduser()

# ---------------------------------------------------------------- frontier
# Optional second tier: a cloud model for the hard questions, while the local
# model keeps doing the cheap routine work. Leave these blank to disable.
#
#   ATLAS_FRONTIER_BASE_URL=https://api.deepseek.com/v1
#   ATLAS_FRONTIER_API_KEY=sk-...
#   ATLAS_FRONTIER_MODEL=deepseek-chat
#
FRONTIER_BASE_URL = os.getenv("ATLAS_FRONTIER_BASE_URL", "")
FRONTIER_API_KEY = os.getenv("ATLAS_FRONTIER_API_KEY", "")
FRONTIER_MODEL = os.getenv("ATLAS_FRONTIER_MODEL", "")
FRONTIER_READY = bool(FRONTIER_BASE_URL and FRONTIER_API_KEY and FRONTIER_MODEL)


def provider_for_base_url(base_url: str) -> str:
    """Which registry entry does an endpoint belong to? '' = custom/remote."""
    target = _root(_clean(base_url))
    for key, preset in PROVIDERS.items():
        if target == _root(preset["base_url"]):
            return key
    return ""
