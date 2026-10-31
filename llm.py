"""The model layer. One function: chat(). Swap providers with an env var.

Nothing clever lives here. The whole point is that you can read this file
in 30 seconds and know exactly what talks to the model.
"""

from __future__ import annotations

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
        **options,
    )
    return response.choices[0].message
