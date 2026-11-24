"""Local answer-quality and user-feedback signals.

Tool success alone is a weak reward: a tool can succeed while the answer still
misses the point. This module adds two local signals without any cloud service:

  1. a cheap deterministic grader (always on), and optionally a small model
     grader (ATLAS_FEEDBACK_MODEL_GRADE=1);
  2. implicit user feedback from the next message ("thanks", "that's wrong").

Both update the same Beta/Thompson tool policy and the stored plan examples,
so the local learning loop improves from answer quality, not just tool ok/error.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time

import config
import examples
import llm
import profiles
import toolpolicy

DB = config.ROOT_DATA / "atlas.db"

_NEGATIVE = re.compile(
    r"^(?:no|nope|wrong|incorrect|not quite|that'?s (?:not|wrong)|you didn'?t|"
    r"try again|redo|do it again|i asked for|thats wrong)\b|"
    r"\b(?:doesn'?t answer|not what i asked|you ignored|missed the point|"
    r"stop saying|hallucinat\w*|made up)\b",
    re.I,
)
_POSITIVE = re.compile(
    r"^(?:thanks|thank you|great|perfect|exactly|yes|good|nice|awesome|"
    r"that'?s it|well done)\b|"
    r"\b(?:that answered it|exactly what i needed|good answer)\b",
    re.I,
)


def classify(text: str) -> int:
    """-1 correction, +1 approval, 0 no signal."""
    value = str(text or "").strip()
    if not value:
        return 0
    if _NEGATIVE.search(value):
        return -1
    if _POSITIVE.search(value):
        return 1
    return 0


def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS feedback_last (
               user_id  TEXT PRIMARY KEY,
               sig      TEXT NOT NULL,
               tools    TEXT NOT NULL,
               answer   TEXT NOT NULL,
               ts       INTEGER NOT NULL
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS feedback_events (
               id       INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id  TEXT NOT NULL,
               sig      TEXT NOT NULL,
               reward   REAL NOT NULL,
               source   TEXT NOT NULL,
               ts       INTEGER NOT NULL
           )"""
    )
    return conn


GRADE_SYSTEM = """Return JSON ONLY: {"score":0.0}.
Score how well the answer fulfils the goal, using only the observed tool
results: 1.0 complete, 0.0 wrong or missing. Never reward invented claims."""


def grade(goal: str, answer: str, observations: str, tier: str = "local",
          model: str | None = None) -> float:
    """Deterministic first; optional small-model grading on top."""
    text = str(answer or "").strip()
    tools_ok = "ok=True" in observations or "ok=true" in observations
    base = 0.45
    if tools_ok:
        base += 0.2
    if len(text) >= 40:
        base += 0.15
    if not any(marker in text.lower() for marker in (
        "no answer", "could not establish", "permission required", "failed"
    )):
        base += 0.1
    if "http" in text:
        base += 0.1
    base = min(0.95, base)

    if os.getenv("ATLAS_FEEDBACK_MODEL_GRADE", "0") != "1":
        return round(base, 2)
    try:
        reply = llm.chat(
            [{"role": "system", "content": GRADE_SYSTEM},
             {"role": "user", "content":
              f"Goal: {goal}\nObservations:\n{observations[:2500]}\nAnswer: {text[:1200]}"}],
            None, tier=tier, model=model, temperature=0, timeout=12,
            max_tokens=80, response_format={"type": "json_object"},
        )
        data = json.loads(reply.content or "{}")
        score = float(data.get("score", base))
        return round(max(0.0, min(1.0, 0.5 * base + 0.5 * score)), 2)
    except Exception:
        return round(base, 2)


def apply(goal: str, tools: list[dict], reward: float, source: str = "grader") -> None:
    """Fold a reward into tool scores and the saved plan's quality."""
    sig = toolpolicy.signature(goal)
    used = list(dict.fromkeys(str(step.get("tool")) for step in tools if step.get("tool")))
    for name in used:
        toolpolicy.reward(sig, name, reward * 2 - 1)
    examples.rate(goal, reward)
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO feedback_events (user_id, sig, reward, source, ts) "
                "VALUES (?,?,?,?,?)",
                (profiles.active(), sig, float(reward), source, int(time.time())),
            )
    except (sqlite3.Error, OSError):
        pass


def note(goal: str, tools: list[dict], answer: str) -> None:
    """Remember which tools produced the last answer for follow-up feedback."""
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO feedback_last (user_id, sig, tools, answer, ts) "
                "VALUES (?,?,?,?,?)",
                (profiles.active(), toolpolicy.signature(goal),
                 json.dumps([str(step.get("tool")) for step in tools]),
                 str(answer)[:600], int(time.time())),
            )
    except (sqlite3.Error, OSError, TypeError, ValueError):
        pass


def followup(text: str) -> dict | None:
    """Apply implicit user feedback from a correction or thanks."""
    signal = classify(text)
    if not signal:
        return None
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT sig, tools, ts FROM feedback_last WHERE user_id=?",
                (profiles.active(),),
            ).fetchone()
            if not row or time.time() - row[2] > 1800:
                return None
            conn.execute("DELETE FROM feedback_last WHERE user_id=?", (profiles.active(),))
            tool_names = json.loads(row[1] or "[]")
    except (sqlite3.Error, OSError, json.JSONDecodeError, TypeError):
        return None
    reward = 1.0 if signal > 0 else 0.0
    tools = [{"tool": name} for name in tool_names]
    apply(row[0], tools, reward, "user")
    return {"tools": tool_names, "reward": reward,
            "kind": "approval" if signal > 0 else "correction"}


def finish(goal: str, tools: list[dict], answer: str, observations: str,
           tier: str = "local", model: str | None = None) -> float:
    """Grade one completed goal run and record it for future turns."""
    score = grade(goal, answer, observations, tier, model)
    if tools:
        apply(goal, tools, score, "grader")
    note(goal, tools, answer)
    return score
