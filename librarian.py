<<<<<<< HEAD
"""The librarian: a cheap second call that decides what is worth remembering.

A 3B model calls tools correctly about half the time. If memory depended on
the model *choosing* to save something, facts would vanish silently. So every
turn gets this second, JSON-constrained pass.

The guards in `plausible()` are the important part. Without them a small model
writes "The user wants to learn about pointers" into permanent memory, and
then it will believe that forever.
=======
"""The librarian: a second, tiny model call whose only job is to decide
what is worth remembering.

Why this exists
---------------
A 3B model calls tools correctly only about half the time. If saving memory
depended on the model *choosing* to call remember(), you would silently lose
facts and never know why. Never let the important path depend on a small
model's good mood.

So the harness does two things every turn:

  1. chat with the model, tools available (best effort, immediate)
  2. ask a cheap JSON-only question: "what here is durable?"  (guaranteed)

Step 2 uses `response_format={"type":"json_object"}`, which constrains the
output to valid JSON. That's far more reliable than tool choice.

    uv run python librarian.py "I use VS Code and I'm learning Python"
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
"""

from __future__ import annotations

import json
import re

import memory
from llm import chat

<<<<<<< HEAD
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
=======
SYSTEM = """You extract durable facts about the user from a single message.

A durable fact is something that stays true next week:
  preferences, skills, tools they use, decisions, names, projects, goals.

Not durable: questions, small talk, one-off requests, things you infer
or guess, facts about the assistant, temporary states ("I'm tired").

Reply with JSON only, in this exact shape:
{"facts": ["one self-contained sentence", "..."]}

Hard rules:
- Quote the user's own claim. Never draw conclusions about their motives,
  interests, feelings, or personality.
- Never describe the conversation ("the user asked", "expressed interest
  in", "wants to discuss"). Those are not facts.
- Only facts the user stated. If the message is a question, return
  {"facts": []}
- Write each fact in the third person, starting with "The user".
- 0 to 3 facts. Fewer is better than invented.
- If nothing is durable, return {"facts": []}
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
"""

META = (
    "interest", "interested", "curious", "asked", "asking", "question",
    "conversation", "discuss", "wants", "needs", "is trying", "is looking",
    "would like", "seems", "appears", "feels", "you can", "you should",
<<<<<<< HEAD
    "is struggling", "frustrated",
)

=======
)  #: words that reveal an invented meta-fact or an echoed answer

#: a real fact about a person is stated, not inferred: it starts like this
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
STARTS = ("the user", "i ", "i'm", "i\u2019m", "i've", "my ", "we ", "our ")


def statements(message: str) -> str:
<<<<<<< HEAD
    """Drop the questions, keep the claims.

    "I run Windows on a 2060. What model fits?" -> "I run Windows on a 2060."
=======
    """Keep only the declarative sentences from a message.

    "I use PyCharm. How do I open a project?" -> "I use PyCharm."
    This is how you get the fact without swallowing the question.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    """
    parts = re.split(r"(?<=[.!?])\s+", message.strip())
    return " ".join(p for p in parts if not p.strip().endswith("?")).strip()


<<<<<<< HEAD
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
=======
def extract(message: str, limit: int = 3) -> list[str]:
    """Return durable facts from one user message. Never raises."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
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


<<<<<<< HEAD
if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "I'm learning C and I have an RTX 2060."
=======
def plausible(fact: str, message: str) -> bool:
    """Cheap guard against invented facts. Three independent tests:

    1. it must be *stated* as a fact about a person ("The user ...", "I ..."),
       not an instruction or a summary of the assistant's own answer;
    2. it must not describe the conversation or infer a motive;
    3. it must share a real word with what the user actually said.
    """
    text = fact.strip().lower()
    if not text.startswith(STARTS):
        return False
    if any(marker in text for marker in META):
        return False
    return bool(memory.keywords(fact) & memory.keywords(message))


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "I'm learning Python and I use VS Code."
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    for fact in extract(text):
        print("-", fact)
