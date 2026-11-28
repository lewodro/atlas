"""Turn verified successes into reusable skills.

Atlas already stores successful plans and feedback locally. This module goes
one step further: a run that reached its goal with a good grade is distilled
into a small SKILL.md recipe. Recipes stay in the local database until the user
explicitly installs one into the repository's skills/ folder, so nothing is
written to tracked files automatically.

No secrets or file bodies are copied into a recipe — tool arguments are kept
as short, redacted shapes only.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time

import config
import profiles
import toolpolicy

DB = config.ROOT_DATA / "atlas.db"
SKILLS = config.ROOT / "skills"
MIN_SCORE = 0.75
_REDACT = {"content", "note", "api_key", "text"}


def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS forged_skills (
               id        TEXT PRIMARY KEY,
               user_id   TEXT NOT NULL,
               goal      TEXT NOT NULL,
               name      TEXT NOT NULL,
               tags      TEXT NOT NULL,
               body      TEXT NOT NULL,
               score     REAL NOT NULL,
               created   INTEGER NOT NULL,
               installed INTEGER NOT NULL DEFAULT 0
           )"""
    )
    return conn


def _recipe_id(goal: str) -> str:
    return "learned-" + hashlib.sha1(
        toolpolicy.signature(goal).encode("utf-8")
    ).hexdigest()[:8]


def _args_shape(args: dict) -> dict:
    out = {}
    for key, value in (args or {}).items():
        if key in _REDACT:
            out[key] = "<provided at run time>"
        elif isinstance(value, str):
            out[key] = value[:80]
        else:
            out[key] = value
    return out


def forge(goal: str, steps: list[dict], score: float) -> dict | None:
    if score < MIN_SCORE or len(steps) < 2:
        return None
    goal = str(goal or "").strip()
    if not goal:
        return None
    identifier = _recipe_id(goal)
    lines = [
        "# Forged skill",
        "",
        "Distilled from a locally verified Atlas run. Reproduce the sequence, "
        "then verify each observation before claiming success.",
        "",
    ]
    tools = []
    for index, step in enumerate(steps[:8], 1):
        name = str(step.get("tool") or "")
        if name not in tools:
            tools.append(name)
        lines.append(
            f"{index}. Call `{name}` with "
            f"`{json.dumps(_args_shape(step.get('args') or {}), ensure_ascii=False)[:260]}`."
        )
        expect = str(step.get("expect") or "").strip()
        if expect:
            lines.append(f"   Verify: {expect[:160]}")
    lines += [
        "",
        "Never invent an observation. If a step fails, repair it once and then "
        "report the failure plainly.",
    ]
    name = "Learned: " + (goal[:48] + ("…" if len(goal) > 48 else ""))
    tags = sorted(set([toolpolicy.intent(goal)] + tools))
    body = "\n".join(lines)
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO forged_skills "
                "(id, user_id, goal, name, tags, body, score, created, installed) "
                "VALUES (?,?,?,?,?,?,?,?,0)",
                (identifier, profiles.active(), goal[:400], name,
                 json.dumps(tags), body, float(score), int(time.time())),
            )
    except (sqlite3.Error, OSError, TypeError, ValueError):
        return None
    return {"id": identifier, "name": name, "tags": tags, "score": score}


def list_forged(limit: int = 30) -> list[dict]:
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT id, name, tags, score, installed, goal FROM forged_skills "
                "ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    return [dict(row, tags=json.loads(row["tags"] or "[]")) for row in rows]


def install(identifier: str) -> Path:
    """User-approved copy into skills/. Never called by the harness itself."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM forged_skills WHERE id=?", (identifier,)
        ).fetchone()
    if not row:
        raise ValueError(f"no forged skill {identifier!r}")
    folder = SKILLS / identifier
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "SKILL.md"
    target.write_text(
        f"---\nname: {row['name']}\n"
        f"description: {str(row['goal'])[:180]}\n"
        f"tags: [{', '.join(json.loads(row['tags'] or '[]'))}]\n"
        f"tools: [{', '.join(json.loads(row['tags'] or '[]'))}]\n"
        f"---\n\n{row['body']}\n",
        encoding="utf-8",
    )
    with _conn() as conn:
        conn.execute(
            "UPDATE forged_skills SET installed=1 WHERE id=?", (identifier,)
        )
    return target
