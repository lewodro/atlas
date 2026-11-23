"""Detect when a request deserves a long, structured answer.

Small models default to terse answers. Explicit depth signals in the user's
words override that default without changing the model.
"""

from __future__ import annotations

import re

LONG = (
    "detailed", "in depth", "deep dive", "definitive", "comprehensive",
    "full research", "research report", "long answer", "all details",
    "walk me through", "explain thoroughly", "step by step", "guide me",
    "help me build", "help me understand", "break it down", "elaborate",
)
SHORT = ("one sentence", "brief", "tl;dr", "quick answer", "just the answer")


def is_long(text: str) -> bool:
    low = str(text or "").lower()
    if any(word in low for word in SHORT) and not any(word in low for word in LONG):
        return False
    return any(word in low for word in LONG)


def instruction(text: str) -> str:
    if is_long(text):
        return (
            "DEPTH: detailed. Give a structured answer with headings, 500-900 words, "
            "concrete examples and a short summary. If tools returned sources, name the "
            "real URLs. Do not stop at a one-line answer just to be brief."
        )
    return (
        "DEPTH: concise. Answer directly in a few sentences unless the user asks for depth."
    )
