<<<<<<< HEAD
"""The only file that talks to a model.

Two tiers, one interface:

  tier="local"     your machine / your LAN. Free. Always available.
  tier="frontier"  an optional cloud model (DeepSeek, Claude, GPT...) for the
                   hard questions. Only used when you ask for it.

Routing lives here so the rest of the code doesn't care which model answered.
=======
"""The model layer. One function: chat(). Swap providers with an env var.

Nothing clever lives here. The whole point is that you can read this file
in 30 seconds and know exactly what talks to the model.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
"""

from __future__ import annotations

<<<<<<< HEAD
from openai import OpenAI

from config import (
    API_KEY,
    BASE_URL,
    FRONTIER_API_KEY,
    FRONTIER_BASE_URL,
    FRONTIER_MODEL,
    FRONTIER_READY,
    MODEL,
)

_local = OpenAI(base_url=BASE_URL, api_key=API_KEY)
_frontier = (
    OpenAI(base_url=FRONTIER_BASE_URL, api_key=FRONTIER_API_KEY)
    if FRONTIER_READY
    else None
)


def tier_model(tier: str) -> str:
    if tier == "frontier":
        if _frontier is None:
            raise RuntimeError(
                "frontier tier not configured — set ATLAS_FRONTIER_* in .env"
            )
        return FRONTIER_MODEL
    return MODEL


def chat(messages: list[dict], tools: list[dict] | None = None, tier: str = "local", **options):
    """One completion. Returns the assistant message object."""
    client = _frontier if tier == "frontier" else _local
    if client is None:
        raise RuntimeError("frontier tier not configured — set ATLAS_FRONTIER_* in .env")

    response = client.chat.completions.create(
        model=options.pop("model", tier_model(tier)),
        messages=messages,
        tools=tools,
        temperature=options.pop("temperature", 0.4),
=======
import os

from openai import OpenAI

PROVIDER = os.getenv("BRAIN_PROVIDER", "ollama").lower()
MODEL = os.getenv("BRAIN_MODEL", "")

if PROVIDER == "ollama":
    # Ollama speaks the OpenAI protocol, so the same client works.
    MODEL = MODEL or "qwen2.5:3b"
    _client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
elif PROVIDER == "openai":
    MODEL = MODEL or "gpt-4o-mini"
    _client = OpenAI()  # reads OPENAI_API_KEY
else:
    raise SystemExit(
        f"Unknown BRAIN_PROVIDER={PROVIDER!r}. Use 'ollama' or 'openai'."
    )


def chat(messages: list[dict], tools: list[dict] | None = None, **options):
    """One completion. Returns the assistant message object.

    Extra keyword arguments (temperature, response_format, ...) are passed
    straight through to the API.
    """
    response = _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=tools,
        temperature=options.pop("temperature", 0.3),
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        **options,
    )
    return response.choices[0].message
