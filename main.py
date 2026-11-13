"""The harness.

<<<<<<< HEAD
A harness is a loop: build context -> ask the model -> run the tools it asks
for -> save what matters. Read `turn()` first; everything else is plumbing.

    uv run python main.py                 # chat, default mode
    uv run python main.py --mode tutor
    uv run python main.py --once "explain pointers"
    uv run python main.py --mode review --once "how was my week?"
=======
A harness is a loop: build context -> ask the model -> run the tools it
asks for -> repeat -> save. That is the entire idea. Read `turn()` first.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
"""

from __future__ import annotations

import json
import re
import sys
<<<<<<< HEAD
import time

import activity
import librarian
import memory
import modes
from config import FRONTIER_READY, MODEL, WHERE
from llm import chat, tier_model

# ---------------------------------------------------------------- tools
=======

import librarian
import memory
from llm import MODEL, PROVIDER, chat

SYSTEM = """You are my second brain: a patient assistant with a long memory.

How to behave:
- Be concise. No filler, no flattery.
- When I tell you something durable about me (a preference, a decision, a
  fact about a project), call remember(). One self-contained fact per call,
  and at most two calls per message.
- Do not remember small talk, one-off questions, or things you are guessing.
- If a note below contradicts me, say so instead of silently updating it.
- If you don't know, say you don't know. Never invent a memory.

Long-term summary (condensed by consolidate.py):
{digest}

Notes that seem relevant to this message:
{relevant}
"""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
<<<<<<< HEAD
            "description": "Save one durable fact about the user (goal, skill, tool, constraint).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "One self-contained sentence."},
                    "tags": {"type": "array", "items": {"type": "string"}},
=======
            "description": "Save one durable fact about the user or their projects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "A single self-contained sentence.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional short tags, e.g. ['python', 'work'].",
                    },
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
<<<<<<< HEAD
            "description": "Search saved notes about the user.",
=======
            "description": "Look through saved notes for something specific.",
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
<<<<<<< HEAD
    {
        "type": "function",
        "function": {
            "name": "recent_activity",
            "description": "Git commits and edited files from the last N hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Default 24."}
                },
            },
        },
    },
]

_activity_cache: dict[int, tuple[float, str]] = {}


def activity_block(hours: int = 24) -> str:
    """Cached: walking ~/dev is not free."""
    now = time.time()
    cached = _activity_cache.get(hours)
    if cached and now - cached[0] < 300:
        return cached[1]
    text = activity.summary(hours)
    _activity_cache[hours] = (now, text)
    return text


def build_system(mode: str, user_text: str) -> str:
    notes = memory.recall(user_text)
    if memory.digest():
        notes = memory.digest() + ("\n\n" + notes if notes else "")
    return modes.build(mode, notes, activity_block())


# ---------------------------------------------------------------- plumbing

TOOL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
ECHO = ("already known:", "saved as notes/", "no notes matched", "refused:")
=======
]


def build_system(user_text: str) -> str:
    return SYSTEM.format(
        digest=memory.digest() or "(nothing consolidated yet)",
        relevant=memory.recall(user_text) or "(nothing found)",
    )
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe


def run_tool(name: str, args: dict, user_text: str = "") -> str:
    if name == "remember":
        text = args.get("text", "").strip()
<<<<<<< HEAD
=======
        # Same guard as the librarian: only save things I actually said.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        if not librarian.plausible(text, user_text):
            return "Refused: that is not a fact the user stated."
        known = memory.find_note(text)
        path = memory.remember(text, args.get("tags"))
        return f"Already known: {path.name}" if known else f"Saved as notes/{path.name}"
    if name == "search_notes":
        return memory.recall(args.get("query", "")) or "No notes matched."
<<<<<<< HEAD
    if name == "recent_activity":
        return activity_block(int(args.get("hours", 24)))
    return f"Unknown tool: {name}"


def salvage(text: str, user_text: str = "") -> str:
    """Small models leak raw <tool_call> tags into prose. Run them, hide them."""
=======
    return f"Unknown tool: {name}"


def journal(user_text: str) -> None:
    """The safety net: catch durable facts the model didn't think to save."""
    try:
        for fact in librarian.extract(user_text):
            if memory.find_note(fact):
                continue
            path = memory.remember(fact, ["auto"])
            print(f"  · noted -> notes/{path.name}")
    except Exception:
        pass  # never let note-taking break the conversation


TOOL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def salvage(text: str, user_text: str = "") -> str:
    """Small models sometimes leak a raw <tool_call>{...}</tool_call> tag into
    their prose. Run it, and hide the machinery from the user."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    if "<tool_call>" not in text:
        return text.strip()

    def handle(match: re.Match) -> str:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return ""
<<<<<<< HEAD
        name, args = data.get("name") or "", data.get("arguments") or {}
=======
        name = data.get("name") or ""
        args = data.get("arguments") or {}
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return ""
        if name:
            print(f"  · {name} -> {run_tool(name, args, user_text)}")
        return ""

    text = TOOL_TAG.sub(handle, text)

<<<<<<< HEAD
    if "<tool_call>" in text:  # unterminated
=======
    # unterminated tag (common: the model gets cut off mid-call)
    if "<tool_call>" in text:
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        head, _, tail = text.partition("<tool_call>")
        try:
            clean = tail.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(clean)
            if data.get("name"):
<<<<<<< HEAD
                print(f"  · {data['name']} -> {run_tool(data['name'], data.get('arguments') or {}, user_text)}")
        except Exception:
            pass
        text = head
    return text.strip()


def finish(answer: str, user_text: str, mode: str) -> str:
    answer = salvage(answer, user_text) or "(the model said nothing useful)"
    if answer.lower().startswith(ECHO):
        answer = "Noted."
    memory.log_turn("assistant", answer, mode)
    return answer


def turn(messages: list[dict], user_text: str, mode: str, tier: str = "local") -> str:
    memory.log_turn("user", user_text, mode)
    messages[0] = {"role": "system", "content": build_system(mode, user_text)}
    messages.append({"role": "user", "content": user_text})

    for _ in range(2):  # tools twice, then force prose
        msg = chat(messages, TOOLS, tier=tier)

        assistant: dict = {"role": "assistant", "content": msg.content or ""}
=======
                print(
                    f"  · {data['name']} -> "
                    f"{run_tool(data['name'], data.get('arguments') or {}, user_text)}"
                )
        except Exception:
            pass
        text = head

    return text.strip()


ECHO = ("already known:", "saved as notes/", "no notes matched", "refused:")


def _finish(answer: str, user_text: str = "") -> str:
    answer = salvage(answer, user_text) or "(the model said nothing useful)"
    if answer.lower().startswith(ECHO):
        answer = "Noted."  # it echoed a tool result instead of answering
    memory.log_turn("assistant", answer)
    return answer


def turn(messages: list[dict], user_text: str) -> str:
    """One full user message, including any tool calls the model wants."""
    memory.log_turn("user", user_text)
    messages[0] = {"role": "system", "content": build_system(user_text)}
    messages.append({"role": "user", "content": user_text})

    # Two rounds with tools. Small models sometimes get into a loop of
    # "call tool, call tool, ...", so after two rounds we take the tools
    # away and force a plain answer. Always answer.
    for _ in range(2):
        msg = chat(messages, TOOLS)

        # Rebuild the message by hand instead of model_dump(): fewer surprises.
        assistant = {"role": "assistant", "content": msg.content or ""}
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
<<<<<<< HEAD
                    "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
=======
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments or "{}",
                    },
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
                }
                for c in msg.tool_calls
            ]
        messages.append(assistant)

        if not msg.tool_calls:
<<<<<<< HEAD
            answer = finish(msg.content or "(empty reply)", user_text, mode)
=======
            answer = _finish(msg.content or "(empty reply)", user_text)
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
            journal(user_text)
            return answer

        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
<<<<<<< HEAD
                args = {}
            result = run_tool(call.function.name, args, user_text)
            print(f"  · {call.function.name} -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    messages.append(
        {"role": "user", "content": "Answer directly in a few sentences. No tools."}
    )
    msg = chat(messages, None, tier=tier)
    journal(user_text)
    return finish(msg.content or "(no answer)", user_text, mode)


def journal(user_text: str) -> None:
    """Safety net: catch durable facts the model didn't think to save."""
    try:
        for fact in librarian.extract(user_text):
            if memory.find_note(fact):
                continue
            path = memory.remember(fact, ["auto"])
            print(f"  · noted -> notes/{path.name}")
    except Exception:
        pass


def trim(messages: list[dict], keep: int = 20) -> list[dict]:
=======
                args = {}  # small models sometimes emit broken JSON
            result = run_tool(call.function.name, args, user_text)
            print(f"  · {call.function.name} -> {result}")
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    messages.append(
        {
            "role": "user",
            "content": "Now answer me directly in one or two sentences. Do not call any tools.",
        }
    )
    msg = chat(messages, None)  # no tools: it has to talk to us now
    journal(user_text)
    return _finish(msg.content or "(the model returned nothing)", user_text)


def trim(messages: list[dict], keep: int = 20) -> list[dict]:
    """Keep the system prompt + a window of history that starts on a user turn."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    body = messages[1:][-keep:]
    while body and body[0]["role"] != "user":
        body.pop(0)
    return [messages[0]] + body


<<<<<<< HEAD
# ---------------------------------------------------------------- cli


def parse_args() -> tuple[str, str | None]:
    mode = "coach"
    once: str | None = None
    words: list[str] = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1].lower()
            i += 2
        elif args[i] == "--once" and i + 1 < len(args):
            once = args[i + 1]
            i += 2
        else:
            words.append(args[i])
            i += 1
    if words and once is None:
        once = " ".join(words)
    return mode, once


def main() -> None:
    mode, once = parse_args()
    tier = "frontier" if "--frontier" in sys.argv and FRONTIER_READY else "local"
    if mode not in modes.MODES:
        print(f"unknown mode {mode!r}\n{modes.listing()}")
        return

    print(f"atlas · {modes.get(mode)['blurb']}")
    print(f"      · {tier_model(tier)} on {WHERE} · {len(memory.note_paths())} notes")
    if once is None:
        hint = "  /frontier" if FRONTIER_READY else ""
        print(f"      · /modes  /mode <name>  /today  /notes  /stats{hint}  /quit\n")

    messages = [{"role": "system", "content": ""}] + memory.load_recent(16)

    if once:
        print(turn(messages, once, mode, tier))
=======
def main() -> None:
    print(f"brain · {PROVIDER}/{MODEL} · {len(memory.note_paths())} notes")
    print("commands: /notes  /stats  /quit\n")

    messages = [{"role": "system", "content": ""}] + memory.load_recent(20)

    if len(sys.argv) > 2 and sys.argv[1] == "--once":
        print(turn(messages, " ".join(sys.argv[2:])))
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        return

    while True:
        try:
<<<<<<< HEAD
            line = input(f"[{mode}]> ").strip()
=======
            user = input("you> ").strip()
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        except (EOFError, KeyboardInterrupt):
            print()
            break

<<<<<<< HEAD
        if line in {"/quit", "quit", "exit", "/q"}:
            break
        if not line:
            continue

        if line.startswith("/mode"):
            choice = line.removeprefix("/mode").strip()
            if not choice:
                print(modes.listing())
            elif choice in modes.MODES:
                mode = choice
                print(f"  mode -> {mode}")
            else:
                print(f"  no mode {choice!r}\n{modes.listing()}")
            continue
        if line == "/frontier":
            if not FRONTIER_READY:
                print("  frontier not configured — see COSTS.md")
            else:
                tier = "local" if tier == "frontier" else "frontier"
                print(f"  tier -> {tier} ({tier_model(tier)})")
            continue
        if line == "/modes":
            print(modes.listing())
            continue
        if line == "/today":
            print(activity_block() + "\n")
            continue
        if line == "/notes":
            for p in memory.note_paths():
                print("  ", p.name)
            continue
        if line == "/stats":
            print(f"   {len(memory.note_paths())} notes · {memory.DB_PATH}")
            continue

        try:
            print(f"atlas> {turn(messages, line, mode, tier)}\n")
        except Exception as exc:
            print(f"  ! {type(exc).__name__}: {exc}")
            print("  (is the server running? try `python check.py`)\n")
=======
        if user in {"/quit", "quit", "exit", "/q"}:
            break
        if not user:
            continue
        if user == "/notes":
            for p in memory.note_paths():
                print("  ", p.name)
            continue
        if user == "/stats":
            print(f"   {len(memory.note_paths())} notes · db: {memory.DB_PATH}")
            continue

        try:
            print(f"brain> {turn(messages, user)}\n")
        except Exception as exc:  # beginner-friendly: show it, keep the loop alive
            print(f"  ! {type(exc).__name__}: {exc}\n")
            print("  (is `ollama serve` running? try `python check.py`)\n")
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe

        messages = trim(messages)


if __name__ == "__main__":
    main()
