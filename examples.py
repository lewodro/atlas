"""Retrieve similar successful tool plans from local history.

This is instance-based learning: instead of fine-tuning weights, Atlas stores
plans that worked and looks them up with TF-IDF cosine similarity when planning
a new goal. Everything stays in the user's own SQLite database.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import Counter

import config
import profiles
import toolpolicy

DB = config.ROOT_DATA / "atlas.db"
MAX_EXAMPLES = 300


def _conn():
    conn = sqlite3.connect(DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tool_examples (
               id        INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id   TEXT NOT NULL,
               sig       TEXT NOT NULL,
               goal      TEXT NOT NULL,
               steps     TEXT NOT NULL,
               score     REAL NOT NULL,
               created   INTEGER NOT NULL
           )"""
    )
    return conn


def save(goal: str, steps: list[dict], score: float = 1.0) -> None:
    """Remember a plan that reached its goal."""
    if not steps:
        return
    compact = []
    for step in steps[:8]:
        args = step.get("args", {})
        if isinstance(args, dict):
            args = {
                key: (str(value)[:240] if isinstance(value, str) else value)
                for key, value in args.items()
            }
        compact.append({"tool": step.get("tool"), "args": args,
                        "why": str(step.get("why") or "")[:120]})
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO tool_examples (user_id, sig, goal, steps, score, created) "
                "VALUES (?,?,?,?,?,?)",
                (profiles.active(), toolpolicy.signature(goal), str(goal)[:400],
                 json.dumps(compact, ensure_ascii=False), float(score), int(time.time())),
            )
            conn.execute(
                "DELETE FROM tool_examples WHERE id IN "
                "(SELECT id FROM tool_examples ORDER BY id DESC LIMIT -1 OFFSET ?)",
                (MAX_EXAMPLES,),
            )
    except (sqlite3.Error, OSError, TypeError, ValueError):
        pass


def _tokens(text: str) -> list[str]:
    return [
        word for word in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
        if word not in toolpolicy._STOP
    ]


def _vector(text: str, idf: dict[str, float]) -> dict[str, float]:
    counts = Counter(_tokens(text))
    if not counts:
        return {}
    norm = math.sqrt(sum((count * idf.get(word, 1.0)) ** 2
                         for word, count in counts.items()))
    if not norm:
        return {}
    return {word: count * idf.get(word, 1.0) / norm
            for word, count in counts.items()}


def similar(goal: str, k: int = 2) -> list[dict]:
    """Return the most similar past plans, with their recorded steps."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT goal, steps, score FROM tool_examples "
                "WHERE user_id=? AND score>=0.7 ORDER BY id DESC LIMIT ?",
                (profiles.active(), MAX_EXAMPLES),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    if not rows:
        return []

    documents = [str(row[0]) for row in rows]
    df: Counter = Counter()
    for document in documents:
        df.update(set(_tokens(document)))
    total = len(documents)
    idf = {word: 1.0 + math.log(total / (1 + freq)) for word, freq in df.items()}
    query = _vector(goal, idf)
    if not query:
        return []

    scored = []
    for row, document in zip(rows, documents):
        vector = _vector(document, idf)
        similarity = sum(value * vector.get(word, 0.0) for word, value in query.items())
        if similarity > 0.18:
            try:
                steps = json.loads(row[1])
            except (json.JSONDecodeError, TypeError):
                continue
            scored.append((similarity, str(row[0])[:160], steps[:4]))
    scored.sort(key=lambda item: -item[0])
    return [
        {"similarity": round(score, 2), "goal": goal_text, "steps": steps}
        for score, goal_text, steps in scored[:k]
    ]


def prompt_hint(goal: str) -> str:
    rows = similar(goal)
    if not rows:
        return ""
    lines = ["Similar goals Atlas already completed locally:"]
    for row in rows:
        tools = ", ".join(str(step.get("tool")) for step in row["steps"])
        lines.append(f"- {row['goal']} -> {tools}")
    return "\n".join(lines)
