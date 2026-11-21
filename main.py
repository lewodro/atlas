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
import artifacts
import context
import fstools
import librarian
import netguard
import memory
import profiles
import modes
import registry
import skills
import webtools
import workspace
from config import FRONTIER_READY, MODEL, WHERE
from llm import chat, tier_model

# ---------------------------------------------------------------- tools

def tool_definitions() -> list[dict]:
    """Current, available tool schemas for the model."""
    return registry.definitions()


#: Backwards-compatible constant; callers that need live changes use the function.
TOOLS = tool_definitions()

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


def build_system(mode: str, user_text: str, skill_id: str | None = None) -> str:
    notes = memory.recall(user_text)
    if memory.digest():
        notes = memory.digest() + ("\n\n" + notes if notes else "")
    skill_id = skill_id or FORCE_SKILL or skills.select_skill(user_text)
    # Project skills must reason from tool results, not from a global scan of ~/dev.
    activity = "" if skill_id in ("project-explorer", "github-engineer") else activity_block()
    prompt = modes.build(mode, notes, activity)
    local_card = context.card(user_text, skill_id)
    if local_card:
        prompt += "\n\n" + local_card
    skill = skills.load_skill(skill_id) if skill_id else None
    if skill and skill.get("enabled"):
        prompt += "\n\nSKILL: " + skill["name"] + "\n" + skill["body"][:1400]
    return prompt


# ---------------------------------------------------------------- plumbing

TOOL_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
ECHO = ("already known:", "saved as notes/", "no notes matched", "refused:")


def run_tool(name: str, args: dict, user_text: str = "", *, approved: bool = False) -> str:
    """Thin adapter so old callers keep working; the registry owns execution."""
    result = registry.run(name, args, approved=approved)
    if result.get("error") == registry.NEEDS_APPROVAL:
        answer = input(f"Allow tool {name}? [y/N] ").strip().lower()
        if answer in ("y", "yes"):
            result = registry.run(name, args, approved=True)
    return registry.content(result)


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
    skill_id = skills.select_skill(user_text)
    messages[0] = {"role": "system", "content": build_system(mode, user_text, skill_id)}
    messages.append({"role": "user", "content": user_text})

    for _ in range(4):  # bounded multi-tool loop, then force prose
        msg = chat(messages, tool_definitions(), tier=tier)
        assistant: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
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
            approved = registry.permission(call.function.name, args) != "ASK"
            if not approved:
                answer = input(f"Allow tool {call.function.name}? [y/N] ").strip().lower()
                approved = answer in ("y", "yes")
            result = registry.run(call.function.name, args, approved=approved)
            if result.get("error") == registry.NEEDS_APPROVAL:
                content = "Permission denied by user."
            else:
                content = registry.content(result)
            print(f"  · {call.function.name} -> {content[:100]}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

    messages.append({"role": "user", "content": "Answer directly in a few sentences. No tools."})
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


FORCE_SKILL: str | None = None


def parse_args() -> tuple[str, str | None]:
    global FORCE_SKILL
    mode = modes.DEFAULT
    once: str | None = None
    words: list[str] = []
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--study":
            FORCE_SKILL = "study"
            i += 1
        elif args[i] == "--mode" and i + 1 < len(args):
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
