"""The harness.

A harness is a loop: build context -> ask the model -> run the tools it
asks for -> repeat -> save. That is the entire idea. Read `turn()` first.
"""

from __future__ import annotations

import json
import re
import sys

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

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
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
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Look through saved notes for something specific.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def build_system(user_text: str) -> str:
    return SYSTEM.format(
        digest=memory.digest() or "(nothing consolidated yet)",
        relevant=memory.recall(user_text) or "(nothing found)",
    )


def run_tool(name: str, args: dict, user_text: str = "") -> str:
    if name == "remember":
        text = args.get("text", "").strip()
        # Same guard as the librarian: only save things I actually said.
        if not librarian.plausible(text, user_text):
            return "Refused: that is not a fact the user stated."
        known = memory.find_note(text)
        path = memory.remember(text, args.get("tags"))
        return f"Already known: {path.name}" if known else f"Saved as notes/{path.name}"
    if name == "search_notes":
        return memory.recall(args.get("query", "")) or "No notes matched."
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
    if "<tool_call>" not in text:
        return text.strip()

    def handle(match: re.Match) -> str:
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return ""
        name = data.get("name") or ""
        args = data.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return ""
        if name:
            print(f"  · {name} -> {run_tool(name, args, user_text)}")
        return ""

    text = TOOL_TAG.sub(handle, text)

    # unterminated tag (common: the model gets cut off mid-call)
    if "<tool_call>" in text:
        head, _, tail = text.partition("<tool_call>")
        try:
            clean = tail.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(clean)
            if data.get("name"):
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
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments or "{}",
                    },
                }
                for c in msg.tool_calls
            ]
        messages.append(assistant)

        if not msg.tool_calls:
            answer = _finish(msg.content or "(empty reply)", user_text)
            journal(user_text)
            return answer

        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
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
    body = messages[1:][-keep:]
    while body and body[0]["role"] != "user":
        body.pop(0)
    return [messages[0]] + body


def main() -> None:
    print(f"brain · {PROVIDER}/{MODEL} · {len(memory.note_paths())} notes")
    print("commands: /notes  /stats  /quit\n")

    messages = [{"role": "system", "content": ""}] + memory.load_recent(20)

    if len(sys.argv) > 2 and sys.argv[1] == "--once":
        print(turn(messages, " ".join(sys.argv[2:])))
        return

    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

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

        messages = trim(messages)


if __name__ == "__main__":
    main()
