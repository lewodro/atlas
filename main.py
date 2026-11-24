"""The harness.

A harness is a loop: build context -> ask the model -> run the tools it asks
for -> save what matters. Read `turn()` first; everything else is plumbing.

    uv run python main.py                 # chat, default mode
    uv run python main.py --mode tutor
    uv run python main.py --once "explain pointers"
    uv run python main.py --mode review --once "how was my week?"
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import activity
import agent
import artifacts
import context
import freshness
import fstools
import feedback
import librarian
import netguard
import memory
import profiles
import modes
import orchestrator
import registry
import skills
import toolcalls
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
    plan = orchestrator.plan(user_text)
    skill_ids = list(plan["skills"])
    chosen = skill_id or FORCE_SKILL
    if chosen and chosen not in skill_ids:
        skill_ids.insert(0, chosen)
    if not skill_ids:
        fallback = skills.select_skill(user_text)
        if fallback:
            skill_ids.append(fallback)
    # Project skills must reason from tool results, not from a global scan of ~/dev.
    activity = "" if any(s in skill_ids for s in ("project-explorer", "github-engineer")) else activity_block()
    prompt = modes.build(mode, notes, activity)
    prompt += f"\n\nCURRENT DATE: {datetime.date.today().isoformat()} (system clock)."
    prompt += f"\n\nAGENT ROLE: {plan['role']}"
    local_card = context.card(user_text, skill_id)
    if local_card:
        prompt += "\n\n" + local_card
    for sid in skill_ids[:2]:
        skill = skills.load_skill(sid)
        if skill and skill.get("enabled"):
            prompt += "\n\nSKILL: " + skill["name"] + "\n" + skill["body"][:1100]
    if freshness.required(user_text) and freshness.web_available():
        prompt += "\n\n" + freshness.directive(user_text)
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
    """Legacy safety net: run calls leaked into prose, hide the raw markup.

    The main loop now repairs calls *before* the final answer (see turn()), so
    their results reach the model. This still covers callers that use finish()
    directly.
    """
    calls, clean = toolcalls.extract(text)
    for call in calls:
        print(f"  · {call['name']} -> {run_tool(call['name'], call['arguments'], user_text)}")
    return clean


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
    """One turn. Time-sensitive requests cannot finish without a web search."""
    memory.log_turn("user", user_text, mode, memory.cli_session())
    try:
        feedback.followup(user_text)
    except Exception:
        pass
    fresh = freshness.required(user_text) and freshness.web_available()
    label = freshness.period(user_text) if fresh else ""
    skill_id = "web-research" if fresh else skills.select_skill(user_text)
    messages[0] = {"role": "system", "content": build_system(mode, user_text, skill_id)}
    messages.append({"role": "user", "content": user_text})
    tracker = freshness.Tracker(fresh, label)
    steps = 0
    planned = False

    def complete(answer: str, *, remember: bool = True) -> str:
        result = finish(answer, user_text, mode)
        if write_memory and remember:
            journal(user_text)
        return result

    # Action requests go through the goal-driven executor first, regardless of
    # whether the model can emit native tool calls. This keeps planning,
    # observation and replanning identical across small and larger models.
    if agent.needs_actions(user_text) and os.getenv("ATLAS_USE_GOALRUNNER", "1") != "0":
        import goalrunner
        outcome = goalrunner.run(
            user_text, tier=tier,
            on_event=lambda item: print(f"  · {item.get('step', '')}", flush=True),
        )
        if outcome["steps"]:
            return complete(outcome["answer"])

    for _ in range(4):  # bounded multi-tool loop
        msg = chat(messages, tool_definitions(), tier=tier)
        content = msg.content or ""
        calls: list[dict] = []
        for item in (msg.tool_calls or []):
            try:
                args = json.loads(item.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": item.id, "name": item.function.name, "arguments": args})

        # Repair calls leaked into prose and feed results back into the loop.
        repaired, clean = toolcalls.extract(content)
        for i, call in enumerate(repaired):
            call["id"] = call.get("id") or f"repair_{i}"
            calls.append(call)

        assistant: dict = {"role": "assistant", "content": clean if repaired else content}
        if calls:
            assistant["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"],
                              "arguments": json.dumps(c["arguments"])}}
                for c in calls
            ]
        messages.append(assistant)

        if not calls:
            # The model narrated instead of calling. The harness performs one
            # bounded search itself so a small model cannot skip research.
            if tracker.blocked() and tracker.can_auto_search():
                queries = freshness.suggest_queries(user_text)
                index = tracker.auto_searches
                query = (queries[index] if index < len(queries)
                         else (queries[0] if queries else f"{label} news"))
                tracker.auto_searches += 1
                cid = f"auto_search_{tracker.auto_searches}"
                auto, info = freshness.auto_tool_messages(
                    "web_search", {"query": query}, cid
                )
                messages.extend(auto)
                tracker.note_call("web_search")
                tracker.note_result("web_search", info["ok"], info["text"])
                messages.append({"role": "user", "content": freshness.grounding_note()})
                print(f"  · web_search (harness) -> {info['text'][:100]}")
                continue
            if tracker.blocked():
                correction = tracker.correct()
                if correction:
                    messages.append({"role": "user", "content": correction})
                    continue
                # Retries exhausted: never substitute stale model knowledge.
                return complete(freshness.failure(label), remember=False)
            if tracker.can_auto_fetch() and tracker.last_search:
                url = freshness.first_url(tracker.last_search)
                if url:
                    tracker.auto_fetches += 1
                    cid = f"auto_fetch_{tracker.auto_fetches}"
                    auto, info = freshness.auto_tool_messages(
                        "web_fetch", {"url": url}, cid
                    )
                    messages.extend(auto)
                    tracker.note_call("web_fetch")
                    messages.append({"role": "user", "content": freshness.grounding_note()})
                    print(f"  · web_fetch (harness) -> {info['text'][:100]}")
                    continue
            nudge = tracker.fetch_nudge()
            if nudge:
                messages.append({"role": "user", "content": nudge})
                continue
            # Models that cannot emit tool calls still get to act: one bounded
            # JSON plan per turn, executed by the harness inside the workspace.
            if not planned and steps == 0 and not tracker.blocked():
                planned = True
                # Last-resort one-shot planner if the goal executor found no
                # safe step (rare: usually a malformed model plan).
                action_plan = agent.plan(user_text, tier=tier)
                if action_plan["actions"]:
                    steps += len(action_plan["actions"])
                    done = agent.execute(action_plan["actions"])
                    for item in done:
                        print(f"  · {item['name']} -> {item['text'][:100]}")
                    report = [
                        {"role": "system", "content": agent.REPORT_SYSTEM},
                        {"role": "user", "content":
                         "User request: " + user_text + "\n\nCompleted tool results:\n"
                         + "\n".join(f"- {i['name']}: {i['text'][:400]}" for i in done)
                         + "\n\nReport concisely in past tense."},
                    ]
                    msg = chat(report, None, tier=tier)
                    return complete(msg.content or action_plan["answer"] or "Done.")
            return complete(content or "(empty reply)")

        for call in calls:
            name, args = call["name"], call["arguments"]
            approved = registry.permission(name, args) != "ASK"
            if not approved:
                answer = input(f"Allow tool {name}? [y/N] ").strip().lower()
                approved = answer in ("y", "yes")
            result = registry.run(name, args, approved=approved)
            tool_text = ("Permission denied by user." if result.get("error") == registry.NEEDS_APPROVAL
                         else registry.content(result))
            steps += 1
            tracker.note_call(name)
            tracker.note_result(name, result["ok"], tool_text)
            print(f"  · {name} -> {tool_text[:100]}")
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": tool_text})

        nudge = tracker.fetch_nudge()
        if nudge:
            messages.append({"role": "user", "content": nudge})

    if tracker.blocked():
        return complete(freshness.failure(label), remember=False)
    messages.append({"role": "user", "content": "Answer directly in a few sentences. No tools."})
    msg = chat(messages, None, tier=tier)
    return complete(msg.content or "(no answer)")


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
            sys.exit(launch_web_gui())

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
