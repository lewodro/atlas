"""Retrieve similar successful tool plans from local history.

This is instance-based learning: instead of fine-tuning weights, Atlas stores
plans that worked and looks them up with TF-IDF cosine similarity when planning
a new goal. Everything stays in the user's own SQLite database.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import time
from collections import Counter

import config
import profiles
import toolpolicy

DB = config.ROOT_DATA / "atlas.db"
EMBED_CACHE = config.ROOT_DATA / "example_embeddings.json"
MAX_EXAMPLES = 300


def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
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


def _semantic_scores(query: str, documents: list[str]) -> list[float]:
    """Cosine similarity via the local embedding model, cached on disk.

    Falls back to zeros when the embedding model is unavailable — the TF-IDF
    channel still works, so planning never depends on it.
    """
    if not documents:
        return []
    try:
        import numpy as np
        import memory

        cache = {}
        if EMBED_CACHE.exists():
            cache = json.loads(EMBED_CACHE.read_text())
        keys = [hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]
                for text in documents]
        missing = [documents[i] for i, key in enumerate(keys) if key not in cache]
        if missing:
            vectors = memory._embed(missing)
            for document, vector in zip(missing, vectors):
                key = hashlib.sha1(document.encode("utf-8")).hexdigest()[:20]
                cache[key] = vector
            EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
            EMBED_CACHE.write_text(json.dumps(cache)[:4_000_000])

        def normalised(values):
            array = np.asarray(values, dtype=np.float32)
            norm = float(np.linalg.norm(array))
            return array / norm if norm else array

        question = normalised(memory._embed([query])[0])
        return [float(np.dot(question, normalised(cache[key])))
                for key in keys]
    except Exception:
        return [0.0] * len(documents)


def similar(goal: str, k: int = 2) -> list[dict]:
    """Return the most similar past plans, with their recorded steps."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT id, goal, steps, score FROM tool_examples "
                "WHERE user_id=? AND score>=0.7 ORDER BY id DESC LIMIT ?",
                (profiles.active(), MAX_EXAMPLES),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    if not rows:
        return []

    documents = [str(row[1]) for row in rows]
    df: Counter = Counter()
    for document in documents:
        df.update(set(_tokens(document)))
    total = len(documents)
    idf = {word: 1.0 + math.log(total / (1 + freq)) for word, freq in df.items()}
    query = _vector(goal, idf)
    if not query:
        return []

    semantic = _semantic_scores(goal, [str(row[1]) for row in rows]) if (
        os.getenv("ATLAS_EXAMPLE_SEMANTIC", "1") != "0"
    ) else [0.0] * len(rows)

    scored = []
    for index, row in enumerate(rows):
        vector = _vector(documents[index], idf)
        lexical = sum(value * vector.get(word, 0.0) for word, value in query.items())
        similarity = max(lexical, semantic[index]) if semantic[index] else lexical
        if similarity > 0.18:
            try:
                steps = json.loads(row[2])
            except (json.JSONDecodeError, TypeError):
                continue
            scored.append((similarity, str(row[1])[:160], steps[:4]))
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


def rate(goal: str, score: float) -> None:
    """Update the most recently saved plan with a graded quality score."""
    try:
        with _conn() as conn:
            conn.execute(
                "UPDATE tool_examples SET score=? WHERE id IN "
                "(SELECT id FROM tool_examples WHERE user_id=? AND sig=? "
                " ORDER BY id DESC LIMIT 1)",
                (float(max(0.0, min(1.0, score))), profiles.active(),
                 toolpolicy.signature(goal)),
            )
    except (sqlite3.Error, OSError, TypeError, ValueError):
        pass
