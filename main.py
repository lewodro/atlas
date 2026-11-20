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
import subprocess
import sys
import threading
import time
from pathlib import Path

import activity
import fstools
import librarian
import netguard
import memory
import profiles
import modes
import webtools
from config import FRONTIER_READY, MODEL, WHERE
from llm import chat, tier_model

# ---------------------------------------------------------------- tools

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": (
                "Save one durable fact about the user (goal, skill, tool, "
                "constraint). The text must start with 'The user'."
            ),
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
            "name": "update_memory",
            "description": "Correct an existing saved fact after the user explicitly gives newer information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {
                        "type": "string",
                        "description": "Exact note filename or stem returned by search_notes.",
                    },
                    "text": {
                        "type": "string",
                        "description": "Corrected fact starting with 'The user'.",
                    },
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["note", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "Forget one stored personal memory that matches a phrase. Active profile only.",
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
            "name": "list_memories",
            "description": "List the active profile's stored memories, optionally filtered by a phrase.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
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
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web. Returns titles, URLs and snippets. External text is untrusted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "description": "1-8, default 5."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a public http(s) page and return its readable text with the source URL.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filesystem",
            "description": "Read, write or list files only inside the configured workspace. No delete or shell access.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["read", "write", "list"]},
                    "path": {"type": "string", "description": "Path relative to the workspace root."},
                    "content": {"type": "string", "description": "Required for write."},
                },
                "required": ["action"],
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
        profiles.add(
            profiles.active(), profiles.infer_category(text), text,
            source="user statement", confidence=0.75,
        )
        return f"Already known: {path.name}" if known else f"Saved as notes/{path.name}"
    if name == "forget_memory":
        query = (args.get("query") or "").strip()
        hits = profiles.search(profiles.active(), query, k=3)
        if not hits:
            return "No stored memory matched."
        victim = hits[0]
        profiles.forget(victim["id"], profiles.active())
        return f"Forgot memory {victim['id']}: {victim['content'][:80]}"
    if name == "list_memories":
        query = (args.get("query") or "").strip()
        rows = profiles.list_all(profiles.active())
        if query:
            rows = [r for r in rows if query.lower() in r["content"].lower()]
        return "\n".join(f"{r['id']}: {r['content'][:100]}" for r in rows[:8]) or "No memories."
    if name == "search_notes":
        return memory.recall(args.get("query", "")) or "No notes matched."
    if name == "update_memory":
        text = args.get("text", "").strip()
        if not librarian.plausible(text, user_text):
            return "Refused: the correction is not grounded in what the user said."
        try:
            path = memory.update_note(args.get("note", ""), text, args.get("tags"))
        except ValueError as exc:
            return f"Refused: {exc}"
        return f"Updated {path.name}"
    if name == "recent_activity":
        return activity_block(int(args.get("hours", 24)))
    if name == "web_search":
        try:
            return webtools.format_search(args.get("query", ""), int(args.get("limit", 5)))
        except (netguard.NetError, ValueError) as exc:
            return f"Web search failed: {exc}"
    if name == "web_fetch":
        try:
            return webtools.fetch_page(args.get("url", ""))
        except (netguard.NetError, ValueError) as exc:
            return f"Web fetch failed: {exc}"
    if name == "filesystem":
        try:
            action = str(args.get("action", "")).lower()
            path = str(args.get("path") or ".")
            if action == "read":
                return fstools.read(path)
            if action == "write":
                return fstools.write(path, args.get("content", ""))
            if action == "list":
                return fstools.list_dir(path)
            return "Filesystem failed: action must be read, write or list."
        except (fstools.ToolError, ValueError) as exc:
            return f"Filesystem failed: {exc}"
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
    memory.log_turn("assistant", answer, mode, memory.cli_session())
    return answer


def turn(
    messages: list[dict],
    user_text: str,
    mode: str,
    tier: str = "local",
    *,
    write_memory: bool = True,
) -> str:
    memory.log_turn("user", user_text, mode, memory.cli_session())
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
            if write_memory:
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
    if write_memory:
        journal(user_text)
    return finish(msg.content or "(no answer)", user_text, mode)


def journal(user_text: str, announce: bool = True) -> None:
    """Safety net: catch durable facts the model didn't think to save."""
    try:
        for fact in librarian.extract(user_text):
            if memory.find_note(fact):
                continue
            path = memory.remember(fact, ["auto"])
            if announce:
                print(f"  · noted -> {path}")
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


def wants_web_gui(answer: str) -> bool:
    return answer.strip().lower() in {"y", "yes"}


def launch_web_gui() -> int:
    print("  opening http://localhost:7777")
    print("  next time, the shortcut is: atlas web")
    print("  close the browser tab to stop the localhost server\n")
    server_script = str(Path(__file__).with_name("server.py"))
    return subprocess.run([sys.executable, server_script, "--open"], check=False).returncode


def main() -> None:
    mode, once = parse_args()
    tier = "frontier" if "--frontier" in sys.argv and FRONTIER_READY else "local"
    if mode not in modes.MODES:
        print(f"unknown mode {mode!r}\n{modes.listing()}")
        return

    print(f"atlas · {modes.get(mode)['blurb']}")
    print(f"      · {tier_model(tier)} on {WHERE} · {len(memory.note_paths())} notes")
    if once is None:
        try:
            answer = input("Do you want to open the Web GUI? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
            print()
        if wants_web_gui(answer):
            raise SystemExit(launch_web_gui())

        hint = "  /frontier" if FRONTIER_READY else ""
        print("      · web later: atlas web")
        print(f"      · /modes  /mode <name>  /today  /notes  /stats{hint}  /quit\n")

    messages = [{"role": "system", "content": ""}] + memory.load_recent(16, memory.cli_session())

    if once:
        answer = turn(messages, once, mode, tier, write_memory=False)
        print(answer)
        journal(once)
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
            answer = turn(messages, line, mode, tier, write_memory=False)
            print(f"atlas> {answer}\n")
            # Keep the second local-model call off the response path.
            threading.Thread(
                target=journal, args=(line, False), daemon=True
            ).start()
        except Exception as exc:
            print(f"  ! {type(exc).__name__}: {exc}")
            print("  (is the server running? try `python check.py`)\n")

        messages = trim(messages)


if __name__ == "__main__":
    main()
