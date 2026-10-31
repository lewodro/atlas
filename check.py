"""Doctor: is everything installed and reachable? Run this first.

    uv run python check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import librarian
import memory
from llm import MODEL, PROVIDER, chat

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "


def check(label: str, fn, required: bool = True) -> str:
    """Run one check. Returns 'ok', 'warn' or 'fail'."""
    try:
        detail, level = fn()
        print(f"[{OK if level == 'ok' else WARN}] {label} — {detail}")
        return level
    except Exception as exc:
        level = "fail" if required else "warn"
        print(f"[{BAD if required else WARN}] {label} — {type(exc).__name__}: {exc}")
        return level


def python_version() -> tuple[str, str]:
    if sys.version_info < (3, 11):
        raise RuntimeError("need Python 3.11+")
    return sys.version.split()[0], "ok"


def deps() -> tuple[str, str]:
    import numpy, openai  # noqa: F401
    return "openai, numpy, pydantic import fine", "ok"


def venv() -> tuple[str, str]:
    if Path(sys.prefix).name != ".venv":
        raise RuntimeError("not in the project venv — use `uv run python check.py`")
    return str(Path(sys.prefix).parent), "ok"


def model_reachable() -> tuple[str, str]:
    reply = chat([{"role": "user", "content": "Reply with the single word: ready"}])
    text = (reply.content or "").strip()
    if not text:
        raise RuntimeError("model returned nothing")
    return f"{MODEL} said {text!r}", "ok"


def tool_calling() -> tuple[str, str]:
    """Not all small models call tools reliably. That's OK — see librarian.py."""
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
    if reply.tool_calls:
        return "tool calls work", "ok"
    return "model sometimes answers in prose; the librarian covers this", "warn"


def librarian_works() -> tuple[str, str]:
    facts = librarian.extract("I'm learning Python and I use VS Code.")
    if not facts:
        raise RuntimeError("extracted nothing from a message with two facts")
    return f"extracted {len(facts)} fact(s)", "ok"


def writable() -> tuple[str, str]:
    memory.log_turn("system", "check.py ping")
    path = memory.remember("check.py wrote this note; safe to delete.")
    path.unlink()
    return "can write to brain.db and notes/", "ok"


def main() -> None:
    print(f"\nbrain doctor · provider={PROVIDER} model={MODEL}\n")
    levels = [
        check("python version", python_version),
        check("project venv", venv),
        check("dependencies", deps),
        check("writable storage", writable),
        check("model reachable", model_reachable),
        check("tool calling", tool_calling, required=False),
        check("memory extraction", librarian_works),
    ]

    print()
    if "fail" in levels:
        print("Fix the FAIL lines above, then run this again.")
        print("Most common cause: Ollama isn't running -> brew services start ollama")
    else:
        print("All good. Start with:  uv run python main.py")
    print()


if __name__ == "__main__":
    main()
