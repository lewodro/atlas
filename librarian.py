"""The librarian: a cheap second call that decides what is worth remembering.

A 3B model calls tools correctly about half the time. If memory depended on
the model *choosing* to save something, facts would vanish silently. So every
turn gets this second, JSON-constrained pass.

The guards in `plausible()` are the important part. Without them a small model
writes "The user wants to learn about pointers" into permanent memory, and
then it will believe that forever.
"""

from __future__ import annotations

import json
import re

import memory
from llm import chat

SYSTEM = """You extract durable facts about a person from one message.

Durable means still true next month:
  goals, skills, what they are learning, tools they use, hardware they own,
  schedule and constraints, decisions they made, how they like to be taught.

NOT durable: questions, small talk, emotional states ("I'm tired"),
one-off requests, anything you infer or guess.

Reply with JSON only:
{"facts": ["one self-contained sentence", "..."]}

Hard rules:
- Quote what the person actually said. Never infer motives, interests,
  personality, or feelings.
- Never describe the conversation ("asked", "wants to know", "expressed
  interest"). Those are not facts.
- If the message is only a question, return {"facts": []}
- Start each fact with "The user".
- 0 to 3 facts. Fewer is better than invented.

Examples:
"I'm 19, studying CS at uni, and my laptop has a 2060."
-> {"facts": ["The user is 19 years old.", "The user studies computer science at university.", "The user owns a laptop with an RTX 2060 GPU."]}

"how do pointers work?"
-> {"facts": []}
"""

META = (
    "interest", "interested", "curious", "asked", "asking", "question",
    "conversation", "discuss", "wants", "needs", "is trying", "is looking",
    "would like", "seems", "appears", "feels", "you can", "you should",
    "is struggling", "frustrated",
)

STARTS = ("the user", "i ", "i'm", "i\u2019m", "i've", "my ", "we ", "our ")


def statements(message: str) -> str:
    """Drop the questions, keep the claims.

    "I run Windows on a 2060. What model fits?" -> "I run Windows on a 2060."
    """
    parts = re.split(r"(?<=[.!?])\s+", message.strip())
    return " ".join(p for p in parts if not p.strip().endswith("?")).strip()


def plausible(fact: str, message: str) -> bool:
    """Three independent guards against invented memory."""
    text = fact.strip().lower()
    if not text.startswith(STARTS):
        return False
    if any(marker in text for marker in META):
        return False
    return bool(memory.keywords(fact) & memory.keywords(message))


def extract(message: str, limit: int = 3) -> list[str]:
    """Durable facts from one user message. Never raises."""
    message = statements(message)
    if len(message) < 12:
        return []

    try:
        reply = chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": message},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(reply.content or "{}")
        facts = [str(f).strip() for f in data.get("facts", []) if str(f).strip()]
    except Exception:
        return []  # memory is a nice-to-have; never break the conversation

    return [f for f in facts if plausible(f, message)][:limit]


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "I'm learning C and I have an RTX 2060."
    for fact in extract(text):
        print("-", fact)
