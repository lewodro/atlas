"""Doctor: is everything installed and reachable? Run this first.

    uv run python check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import memory
from llm import MODEL, PROVIDER, chat

OK, BAD, WARN = "  ok  ", " FAIL ", " warn "


def check(label: str, fn) -> bool:
    try:
        detail = fn()
        print(f"[{OK}] {label}" + (f" — {detail}" if detail else ""))
        return True
    except Exception as exc:
        print(f"[{BAD}] {label} — {type(exc).__name__}: {exc}")
        return False


def python_version() -> str:
    if sys.version_info < (3, 11):
        raise RuntimeError("need Python 3.11+")
    return sys.version.split()[0]


def deps() -> str:
    import numpy, openai  # noqa: F401
    return "openai, numpy, pydantic import fine"


def venv() -> str:
    inside = Path(sys.prefix).name == ".venv"
    if not inside:
        raise RuntimeError("not in the project venv — use `uv run python check.py`")
    return str(Path(sys.prefix).parent)


def model_reachable() -> str:
    reply = chat([{"role": "user", "content": "Reply with the single word: ready"}])
    text = (reply.content or "").strip()
    if not text:
        raise RuntimeError("model returned nothing")
    return f"{MODEL} said {text!r}"


def tool_calling() -> str:
    """Can this model actually call a function? Not all small models can."""
    reply = chat(
        [{"role": "user", "content": "Save the fact 'the sky is blue' using the tool."}],
        tools=[
            {
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
            }
        ],
    )
    if not reply.tool_calls:
        raise RuntimeError("model replied in prose instead of calling the tool")
    return "tool calls work"


def writable() -> str:
    memory.log_turn("system", "check.py ping")
    path = memory.remember("check.py wrote this note; safe to delete.")
    path.unlink()
    return "can write to brain.db and notes/"


def main() -> None:
    print(f"\nbrain doctor · provider={PROVIDER} model={MODEL}\n")
    results = [
        check("python version", python_version),
        check("project venv", venv),
        check("dependencies", deps),
        check("writable storage", writable),
        check("model reachable", model_reachable),
        check("tool calling", tool_calling),
    ]

    print()
    if all(results):
        print("All good. Start with:  uv run python main.py")
    else:
        print("Fix the FAIL lines above, then run this again.")
        print("Most common cause: Ollama isn't running -> brew services start ollama")
    print()


if __name__ == "__main__":
    main()
