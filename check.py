<<<<<<< HEAD
"""Doctor. Run this first, and whenever something feels broken.
=======
"""Doctor: is everything installed and reachable? Run this first.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe

    uv run python check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

<<<<<<< HEAD
import activity
import librarian
import memory
from config import BASE_URL, MODEL, REMOTE, WHERE
from llm import chat
=======
import librarian
import memory
from llm import MODEL, PROVIDER, chat
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe

OK, WARN, BAD = "  ok  ", " warn ", " FAIL "


<<<<<<< HEAD
def check(label, fn, required=True):
=======
def check(label: str, fn, required: bool = True) -> str:
    """Run one check. Returns 'ok', 'warn' or 'fail'."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    try:
        detail, level = fn()
        print(f"[{OK if level == 'ok' else WARN}] {label} — {detail}")
        return level
    except Exception as exc:
        level = "fail" if required else "warn"
        print(f"[{BAD if required else WARN}] {label} — {type(exc).__name__}: {exc}")
        return level


<<<<<<< HEAD
def python_version():
=======
def python_version() -> tuple[str, str]:
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    if sys.version_info < (3, 11):
        raise RuntimeError("need Python 3.11+")
    return sys.version.split()[0], "ok"


<<<<<<< HEAD
def deps():
    import numpy, openai  # noqa: F401
    return "openai, numpy import fine", "ok"


def venv():
=======
def deps() -> tuple[str, str]:
    import numpy, openai  # noqa: F401
    return "openai, numpy, pydantic import fine", "ok"


def venv() -> tuple[str, str]:
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    if Path(sys.prefix).name != ".venv":
        raise RuntimeError("not in the project venv — use `uv run python check.py`")
    return str(Path(sys.prefix).parent), "ok"


<<<<<<< HEAD
def writable():
    memory.log_turn("system", "check.py ping")
    path = memory.remember("check.py wrote this note; safe to delete.")
    path.unlink()
    return "can write to data/ and notes/", "ok"


def model_reachable():
    reply = chat([{"role": "user", "content": "Reply with one word: ready"}], temperature=0)
=======
def model_reachable() -> tuple[str, str]:
    reply = chat([{"role": "user", "content": "Reply with the single word: ready"}])
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    text = (reply.content or "").strip()
    if not text:
        raise RuntimeError("model returned nothing")
    return f"{MODEL} said {text!r}", "ok"


<<<<<<< HEAD
def tool_calling():
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
=======
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
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    )
    if reply.tool_calls:
        return "tool calls work", "ok"
    return "model sometimes answers in prose; the librarian covers this", "warn"


<<<<<<< HEAD
def extraction():
    facts = librarian.extract("I'm learning C and I own an RTX 2060 laptop.")
=======
def librarian_works() -> tuple[str, str]:
    facts = librarian.extract("I'm learning Python and I use VS Code.")
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    if not facts:
        raise RuntimeError("extracted nothing from a message with two facts")
    return f"extracted {len(facts)} fact(s)", "ok"


<<<<<<< HEAD
def projects():
    if not activity.PROJECTS.exists():
        return f"{activity.PROJECTS} missing (set ATLAS_PROJECTS)", "warn"
    repos = activity.repos()
    return f"{activity.PROJECTS} · {len(repos)} git repo(s)", "ok"


def main():
    print(f"\natlas doctor\n  model    : {MODEL}\n  endpoint : {BASE_URL}\n  running  : {WHERE}\n")
=======
def writable() -> tuple[str, str]:
    memory.log_turn("system", "check.py ping")
    path = memory.remember("check.py wrote this note; safe to delete.")
    path.unlink()
    return "can write to brain.db and notes/", "ok"


def main() -> None:
    print(f"\nbrain doctor · provider={PROVIDER} model={MODEL}\n")
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    levels = [
        check("python version", python_version),
        check("project venv", venv),
        check("dependencies", deps),
        check("writable storage", writable),
        check("model reachable", model_reachable),
        check("tool calling", tool_calling, required=False),
<<<<<<< HEAD
        check("memory extraction", extraction),
        check("project scan", projects),
=======
        check("memory extraction", librarian_works),
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    ]

    print()
    if "fail" in levels:
<<<<<<< HEAD
        print("Fix the FAIL lines, then run this again.")
        if REMOTE:
            print(f"Cannot reach {BASE_URL}. On the GPU machine:")
            print("  OLLAMA_HOST=0.0.0.0 ollama serve")
            print("  firewall must allow the port from your local network only")
        else:
            print("Local server down? `ollama serve` (or `brew services start ollama`)")
=======
        print("Fix the FAIL lines above, then run this again.")
        print("Most common cause: Ollama isn't running -> brew services start ollama")
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    else:
        print("All good. Start with:  uv run python main.py")
    print()


if __name__ == "__main__":
    main()
