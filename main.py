"""The harness.

A harness is a loop: build context -> ask the model -> run the tools it asks
for -> save what matters. Read `turn()` first; everything else is plumbing.

    uv run python main.py                 # chat, default mode
    uv run python main.py --mode tutor
    uv run python main.py --once "explain pointers"
    uv run python main.py --mode review --once "how was my week?"
"""

from __future__ import annotations

import json
import re
import sys
import time

import activity
import librarian
import memory
import modes
from config import FRONTIER_READY, MODEL, WHERE
from llm import chat, tier_model

# ---------------------------------------------------------------- tools

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Save one durable fact about the user (goal, skill, tool, constraint).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "One self-contained sentence."},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search saved notes about the user.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
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


def run_tool(name: str, args: dict, user_text: str = "") -> str:
    if name == "remember":
        text = args.get("text", "").strip()
        if not librarian.plausible(text, user_text):
            return "Refused: that is not a fact the user stated."
        known = memory.find_note(text)
        path = memory.remember(text, args.get("tags"))
        return f"Already known: {path.name}" if known else f"Saved as notes/{path.name}"
    if name == "search_notes":
        return memory.recall(args.get("query", "")) or "No notes matched."
    if name == "recent_activity":
        return activity_block(int(args.get("hours", 24)))
    return f"Unknown tool: {name}"


def salvage(text: str, user_text: str = "") -> str:
    """Small models leak raw <tool_call> tags into prose. Run them, hide them."""
    if "<tool_call>" not in text:
        return text.strip()

    def handle(match: re.Match) -> str:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return ""
        name, args = data.get("name") or "", data.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return ""
        if name:
            print(f"  · {name} -> {run_tool(name, args, user_text)}")
        return ""

    text = TOOL_TAG.sub(handle, text)

    if "<tool_call>" in text:  # unterminated
        head, _, tail = text.partition("<tool_call>")
        try:
            clean = tail.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(clean)
            if data.get("name"):
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
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"},
                }
                for c in msg.tool_calls
            ]
        messages.append(assistant)

        if not msg.tool_calls:
            answer = finish(msg.content or "(empty reply)", user_text, mode)
            journal(user_text)
            return answer

        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
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
    body = messages[1:][-keep:]
    while body and body[0]["role"] != "user":
        body.pop(0)
    return [messages[0]] + body


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
        return

    while True:
        try:
            line = input(f"[{mode}]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

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

        messages = trim(messages)


if __name__ == "__main__":
    main()
