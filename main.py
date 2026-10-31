"""The harness.

A harness is a loop: build context -> ask the model -> run the tools it
asks for -> repeat -> save. That is the entire idea. Read `turn()` first.
"""

from __future__ import annotations

import json
import sys

import memory
from llm import MODEL, PROVIDER, chat

SYSTEM = """You are my second brain: a patient assistant with a long memory.

How to behave:
- Be concise. No filler, no flattery.
- When I tell you something durable about me (a preference, a decision, a
  fact about a project), call remember(). One self-contained fact per call.
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


def run_tool(name: str, args: dict) -> str:
    if name == "remember":
        path = memory.remember(args.get("text", ""), args.get("tags"))
        return f"Saved as notes/{path.name}"
    if name == "search_notes":
        return memory.recall(args.get("query", "")) or "No notes matched."
    return f"Unknown tool: {name}"


def turn(messages: list[dict], user_text: str) -> str:
    """One full user message, including any tool calls the model wants."""
    memory.log_turn("user", user_text)
    messages[0] = {"role": "system", "content": build_system(user_text)}
    messages.append({"role": "user", "content": user_text})

    for _ in range(4):  # safety cap: never loop forever
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
            answer = msg.content or "(empty reply)"
            memory.log_turn("assistant", answer)
            return answer

        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}  # small models sometimes emit broken JSON
            result = run_tool(call.function.name, args)
            print(f"  · {call.function.name} -> {result}")
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    return "(stopped: too many tool calls in a row)"


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
