"""The only file that talks to a model.

Two tiers, one interface:

  tier="local"     whatever endpoint is configured: Ollama on this machine,
                   LM Studio, llama.cpp, vLLM, or a GPU box on the LAN.
  tier="frontier"  an optional cloud model (DeepSeek, Claude, GPT...) for the
                   hard questions. Only used when you ask for it.

Endpoint and model come from `models.load()`, which layers
data/settings.json over .env over built-in defaults — so the web UI can
switch models at runtime without a restart.

Not every model supports native tool calling. When a server rejects `tools`,
we retry once without them; main.py's <tool_call> salvage keeps that usable.
"""

from __future__ import annotations

from openai import OpenAI

import config
import models
from config import (
    FRONTIER_API_KEY,
    FRONTIER_BASE_URL,
    FRONTIER_MODEL,
    FRONTIER_READY,
)

_clients: dict[tuple[str, str], OpenAI] = {}

#: Models that turned out not to accept the `tools` parameter.
_no_tools: set[str] = set()


def _budget(model: str) -> int:
    """High ceiling for reasoning checkpoints, modest for normal chat models."""
    low = str(model or "").lower()
    if any(hint in low for hint in config.REASONING_HINTS):
        return config.REASONING_TOKENS
    return config.MAX_TOKENS


def _client(base_url: str, api_key: str) -> OpenAI:
    # openai >= 3.42 refuses an empty api_key. Local servers ignore the value,
    # so a non-empty placeholder is enough. This also covers auto-detection,
    # which deliberately does not read a key from disk.
    api_key = api_key or config.API_KEY or "ollama"
    key = (base_url, api_key)
    client = _clients.get(key)
    if client is None:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=180.0)
        _clients[key] = client
    return client


def active(tier: str = "local") -> tuple[OpenAI, str]:
    """The client and model id for this tier, right now."""
    if tier == "frontier":
        if not FRONTIER_READY:
            raise RuntimeError("frontier tier not configured — set ATLAS_FRONTIER_* in .env")
        return _client(FRONTIER_BASE_URL, FRONTIER_API_KEY), FRONTIER_MODEL

    current = models.load()
    return _client(current["base_url"], current["api_key"]), current["model"]


def tier_model(tier: str = "local") -> str:
    return active(tier)[1]


def _rejects_tools(exc: Exception) -> bool:
    text = str(exc).lower()
    return "tool" in text and ("support" in text or "does not" in text or "not supported" in text)


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    tier: str = "local",
    model: str | None = None,
    **options,
):
    """One completion. Returns the assistant message object."""
    client, default_model = active(tier)
    name = model or default_model
    use_tools = tools if name not in _no_tools else None
    # Bound generation: without this, some local runtimes stream indefinitely
    # and saturate the model server after a few agent turns.
    temperature = options.pop("temperature", 0.4)
    cap = options.setdefault("max_tokens", _budget(name))

    try:
        response = client.chat.completions.create(
            model=name,
            messages=messages,
            tools=use_tools,
            temperature=temperature,
            **options,
        )
    except Exception as exc:
        if use_tools and _rejects_tools(exc):
            _no_tools.add(name)
            return chat(messages, None, tier=tier, model=name,
                        temperature=temperature, **options)
        raise

    message = response.choices[0].message
    choice = response.choices[0]
    # Reasoning models can spend the whole budget thinking and return no text.
    # One bounded retry at a larger cap fixes that without an unbounded server.
    if (not (message.content or "").strip()
            and getattr(choice, "finish_reason", None) == "length" and cap < 8192):
        options["max_tokens"] = min(cap * 2, 8192)
        return chat(messages, tools, tier=tier, model=model,
                    temperature=temperature, **options)
    return message


def stream_chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    tier: str = "local",
    model: str | None = None,
    **options,
):
    """Same call, but streaming. Iterate chunks; each has .choices[0].delta."""
    client, default_model = active(tier)
    name = model or default_model
    use_tools = tools if name not in _no_tools else None
    options.setdefault("max_tokens", _budget(name))

    try:
        return client.chat.completions.create(
            model=name,
            messages=messages,
            tools=use_tools,
            temperature=options.pop("temperature", 0.4),
            stream=True,
            **options,
        )
    except Exception as exc:
        if use_tools and _rejects_tools(exc):
            _no_tools.add(name)
            return stream_chat(messages, None, tier=tier, model=name, **options)
        raise
