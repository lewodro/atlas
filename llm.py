"""The only file that talks to a model.

Two tiers, one interface:

  tier="local"     your machine / your LAN. Free. Always available.
  tier="frontier"  an optional cloud model (DeepSeek, Claude, GPT...) for the
                   hard questions. Only used when you ask for it.

Routing lives here so the rest of the code doesn't care which model answered.
"""

from __future__ import annotations

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
        **options,
    )
    return response.choices[0].message


def stream_chat(messages: list[dict], tools: list[dict] | None = None, tier: str = "local", **options):
    """Same call, but streaming. Iterate chunks; each has .choices[0].delta."""
    client = _frontier if tier == "frontier" else _local
    if client is None:
        raise RuntimeError("frontier tier not configured — set ATLAS_FRONTIER_* in .env")

    return client.chat.completions.create(
        model=options.pop("model", tier_model(tier)),
        messages=messages,
        tools=tools,
        temperature=options.pop("temperature", 0.4),
        stream=True,
        **options,
    )
