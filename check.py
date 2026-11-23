"""Atlas doctor — diagnose a fresh clone, not just the happy path.

    uv run python check.py

It reports setup, config, runtimes, ports, model and memory, and every FAIL
line says how to fix it. It never prints API keys and never raises a traceback.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import socket
import sqlite3
import sys
import time
from pathlib import Path

import config
import librarian
import models
import profiles
import workspace
from llm import chat

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "
STATE: dict = {}


# ------------------------------------------------------------------ helpers

def _safe_error(exc: Exception) -> str:
    """Flatten an exception without leaking a configured key."""
    text = " ".join(str(exc).split())
    secrets = {config.API_KEY, os.getenv("ATLAS_API_KEY", "").strip()}
    for secret in secrets:
        if secret and secret.lower() not in {"ollama", "lmstudio", "llamacpp", "vllm"}:
            text = text.replace(secret, "***")
    return re.sub(r"sk-[A-Za-z0-9._-]{6,}", "***", text)


def check(label: str, fn, required: bool = True) -> str:
    try:
        detail, level = fn()
    except Exception as exc:  # a doctor must never crash on bad config
        detail, level = f"{type(exc).__name__}: {_safe_error(exc)}", (
            "fail" if required else "warn"
        )
    print(f"[{OK if level == 'ok' else BAD if level == 'fail' else WARN}] "
          f"{label} — {detail}")
    return level


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".atlas-check-{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# -------------------------------------------------------------------- checks

def python_version():
    version = sys.version.split()[0]
    if sys.version_info < (3, 12):
        raise RuntimeError(
            f"{version} is too old (need >= 3.12). Install with "
            "`uv python install 3.13` or use pyenv/Homebrew."
        )
    return version + " (need >= 3.12)", "ok"


def venv():
    if Path(sys.prefix).name != ".venv":
        raise RuntimeError(
            "not in the project venv — run `uv sync` then `uv run python check.py`"
        )
    return str(Path(sys.prefix).parent), "ok"


def deps():
    versions = {
        name: importlib.metadata.version(name) for name in ("openai", "numpy")
    }
    return ", ".join(f"{k} {v}" for k, v in versions.items()), "ok"


def env_file():
    path = config.ROOT / ".env"
    if not path.exists():
        return ("no .env (defaults work, but copy it to choose a model): "
                "`cp .env.example .env`", "warn")
    keys = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            keys.append(line.split("=", 1)[0].strip())
    return f"{path} present ({len(keys)} settings)", "ok"


def settings_file():
    path = models.SETTINGS
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
        chosen = data.get("model") or "(unset)"
        return f"{path} overrides .env — model {chosen}", "ok"
    return "none (using .env / provider defaults)", "ok"


def configuration():
    current = models.load()
    provider = config.provider_for_base_url(current["base_url"]) or "custom"
    STATE["provider"] = provider
    STATE["effective_model"] = current["model"]
    configured = f"provider {config.PROVIDER}, ATLAS_MODEL={config.MODEL}"
    return (
        f"{configured}; effective model {current['model']} "
        f"(api key {'set' if current['api_key'] else 'missing'})",
        "ok",
    )


def missing_environment():
    optional = ["ATLAS_MODEL_PROVIDER", "ATLAS_MODEL", "ATLAS_BASE_URL",
                "ATLAS_API_KEY", "ATLAS_OLLAMA_URL"]
    missing = [key for key in optional if not os.getenv(key)]
    if not missing:
        return "all optional overrides provided", "ok"
    return (
        "not set: " + ", ".join(missing) +
        " — defaults work; see .env.example. For Ollama set "
        "ATLAS_MODEL_PROVIDER=ollama and ATLAS_MODEL=deepseek-r1:7b",
        "warn",
    )


def provider_registry():
    names = ", ".join(f"{k} (:{p['port']})" for k, p in config.PROVIDERS.items())
    if config.PROVIDER not in config.PROVIDERS:
        return f"unknown provider {config.PROVIDER!r}; registry has {names}", "warn"
    return names, "ok"


def data_dir():
    path = config.ROOT_DATA
    if not _writable(path):
        raise RuntimeError(
            f"cannot write {path}. Fix permissions or set ATLAS_DATA_DIR to a "
            "folder you own."
        )
    return f"{path} writable", "ok"


def memory_store():
    path = profiles.DB
    if not path.exists():
        raise RuntimeError(
            f"no database at {path}. It is created automatically on first run; "
            "`uv run python check.py` should recreate it."
        )
    with sqlite3.connect(path) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        needed = {"profiles", "memories"}
        if not needed <= tables:
            raise RuntimeError(
                f"{path} is missing tables {sorted(needed - tables)} — delete the "
                "file to let Atlas rebuild it (back it up first if it is yours)."
            )
        memories = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        profile_count = conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    STATE["memories"] = memories
    detail = f"SQLite at {path} · {memories} memories, {profile_count} profile(s)"
    if memories == 0:
        detail += " (fresh/empty — add one with `atlas remember \"I ...\"`)"
    return detail, "ok"


def workspace_config():
    info = workspace.context()
    if not info.get("configured"):
        return (
            "not configured — run `atlas tools configure --workspace ~/dev` or "
            "set ATLAS_WORKSPACE in .env (filesystem/terminal tools stay "
            "unavailable until then)",
            "warn",
        )
    state = "dirty" if info.get("dirty") else "clean"
    return f"{info['root']} · {info.get('repo') or 'no repo'} · {state}", "ok"


def required_ports():
    open_ports = [
        f"{key}:{p['port']}" for key, p in config.PROVIDERS.items()
        if _port_open(p["port"])
    ]
    STATE["open_ports"] = open_ports
    if not open_ports:
        raise RuntimeError(
            "no local model runtime is listening (checked " +
            ", ".join(f":{p['port']}" for p in config.PROVIDERS.values()) +
            "). Start one, e.g. `ollama serve` (or `brew services start ollama`)."
        )
    return "listening: " + ", ".join(open_ports), "ok"


def ollama_status():
    status = models.native_status("ollama")
    if status is None:
        raise RuntimeError(
            "Ollama is not reachable at " + config.OLLAMA_URL +
            ". Fix: `ollama serve` (or `brew services start ollama`), then retry."
        )
    names = [str(m.get("name") or m.get("id") or "") for m in
             (status.get("models") or []) if isinstance(m, dict)]
    STATE["ollama_models"] = names
    return f"reachable at {config.OLLAMA_URL} · {len(names)} model(s)", "ok"


def lmstudio_status():
    status = models.native_status("lmstudio")
    if status is None:
        return "offline on :1234 (optional — only needed if you use LM Studio)", "warn"
    return "reachable on :1234", "ok"


def selected_model_installed():
    current = models.load()
    provider = STATE.get("provider") or "ollama"
    available = models.list_models(current["base_url"], current["api_key"], timeout=3.0)
    STATE["available_models"] = available
    name = current["model"]
    if not available:
        preset = config.PROVIDERS.get(provider, {})
        raise RuntimeError(
            f"no models listed by the {provider} endpoint at {current['base_url']}. "
            f"Fix: {preset.get('install', 'start a model in your runtime')}."
        )
    if name in available:
        return f"{name} is installed on {provider}", "ok"
    if provider == "ollama":
        raise RuntimeError(
            f"Ollama is running, but {name} is not installed. "
            f"Run: ollama pull {name}"
        )
    raise RuntimeError(
        f"{name} is not offered by {provider}. Load it in that runtime "
        "or change ATLAS_MODEL / `atlas use <model>`."
    )


def model_reachable():
    if not STATE.get("available_models"):
        return "skipped — no model endpoint to call", "warn"
    started = time.monotonic()
    reply = chat(
        [{"role": "user", "content": "Reply with exactly one word: ready"}],
        temperature=0, max_tokens=config.MAX_TOKENS, timeout=90,
    )
    text = (reply.content or "").strip()
    if not text:
        text = str(getattr(reply, "reasoning_content", "") or "").strip()
    if not text:
        raise RuntimeError(
            f"{STATE.get('effective_model')} returned an empty reply. Try a "
            "larger ATLAS_MAX_TOKENS (reasoning models spend tokens thinking)."
        )
    elapsed = time.monotonic() - started
    return f"{STATE.get('effective_model')} said {text[:40]!r} in {elapsed:.1f}s", "ok"


def tool_calling():
    if not STATE.get("available_models"):
        return "skipped — no model endpoint to call", "warn"
    reply = chat(
        [{"role": "user", "content": "Save the fact 'the sky is blue' using the tool."}],
        tools=[{
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Save a fact.",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }],
        max_tokens=config.MAX_TOKENS, timeout=90,
    )
    if reply.tool_calls:
        return "native tool calls work", "ok"
    return "model answered in prose; the librarian/deterministic fallback covers this", "warn"


def extraction():
    if not STATE.get("available_models"):
        return "skipped — no model endpoint to call", "warn"
    facts = librarian.extract("I'm learning C and I own an RTX 2060 laptop.")
    if not facts:
        return ("extracted no facts — check the model reachable line; memory "
                "writes need a working JSON model call", "warn")
    return f"extracted {len(facts)} fact(s)", "ok"


def embedding_model():
    names = STATE.get("ollama_models")
    if names is None:
        return "Ollama offline — keyword retrieval is the fallback", "warn"
    embed = os.getenv("ATLAS_EMBED_MODEL", "nomic-embed-text")
    if any(embed in name for name in names):
        return f"{embed} installed (semantic recall available)", "ok"
    return (f"{embed} not installed — keyword recall still works. "
            f"Fix: ollama pull {embed}", "warn")


def notes_dir():
    path = config.ROOT_NOTES
    if not _writable(path):
        raise RuntimeError(
            f"cannot write {path}. Fix permissions or set ATLAS_NOTES_DIR in .env."
        )
    count = len(list(path.glob("*.md")))
    return f"{path} writable · {count} note(s)", "ok"


# ---------------------------------------------------------------------- main

def main() -> None:
    current = models.load()
    provider = config.provider_for_base_url(current["base_url"]) or "custom"
    print("\natlas doctor — setup & runtime diagnostics")
    print(f"  provider  : {provider} ({config.PROVIDER} configured)")
    print(f"  endpoint  : {current['base_url']}")
    print(f"  model     : {current['model']} (effective)")
    source = "auto-detected" if not (os.getenv("ATLAS_MODEL") or models.SETTINGS.exists()) \
        else "configured"
    print(f"  default   : {config.MODEL} · ATLAS_MODEL_PROVIDER={config.PROVIDER} "
          f"({source})")
    print(f"  data dir  : {config.ROOT_DATA}")
    print(f"  notes dir : {config.ROOT_NOTES}\n")

    levels = [
        check("python version", python_version),
        check("project venv", venv),
        check("dependencies", deps),
        check(".env file", env_file, required=False),
        check("runtime settings", settings_file, required=False),
        check("configuration", configuration),
        check("environment variables", missing_environment, required=False),
        check("provider registry", provider_registry, required=False),
        check("local data dir", data_dir),
        check("memory store", memory_store),
        check("workspace config", workspace_config, required=False),
        check("required ports", required_ports),
        check("Ollama", ollama_status, required=(provider == "ollama")),
        check("LM Studio", lmstudio_status, required=False),
        check("selected model installed", selected_model_installed),
        check("model reachable", model_reachable),
        check("tool calling", tool_calling, required=False),
        check("memory extraction", extraction, required=False),
        check("embedding model", embedding_model, required=False),
        check("notes dir", notes_dir),
    ]

    print()
    if "fail" in levels:
        print("Fix the FAIL lines above, then run `uv run python check.py` again.")
    else:
        print("All good. Start with:  uv run python main.py   (or: atlas web)")
        if STATE.get("memories", 0) == 0:
            print("Fresh memory: add a fact with `atlas remember \"I ...\"` or just chat.")
    print()


if __name__ == "__main__":
    main()
