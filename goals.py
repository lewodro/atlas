"""Goal state for the agent. Stored locally per profile.

A goal is an objective the agent works toward across tool calls and turns.
This module only stores state — the loop lives in the server.
"""

from __future__ import annotations

import json
import time
import uuid

import config
import profiles

DB = config.ROOT_DATA / "atlas.db"
ACTIVE = {"active", "running", "paused"}


def _conn():
    import sqlite3

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS goals (
               id       TEXT PRIMARY KEY,
               user_id  TEXT NOT NULL,
               text     TEXT NOT NULL,
               status   TEXT NOT NULL,
               notes    TEXT NOT NULL DEFAULT '[]',
               created  INTEGER NOT NULL,
               updated  INTEGER NOT NULL
           )"""
    )
    return conn


def create(text: str, user: str | None = None) -> dict:
    text = str(text or "").strip()
    if not text:
        raise ValueError("goal text is empty")
    row = {
        "id": "g-" + uuid.uuid4().hex[:8],
        "user_id": user or profiles.active(),
        "text": text,
        "status": "active",
        "notes": "[]",
        "created": int(time.time()),
        "updated": int(time.time()),
    }
    with _conn() as conn:
        conn.execute(
            "INSERT INTO goals (id, user_id, text, status, notes, created, updated) "
            "VALUES (:id, :user_id, :text, :status, :notes, :created, :updated)", row,
        )
    return row


def current(user: str | None = None) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM goals WHERE user_id = ? AND status IN ('active','running','paused') "
            "ORDER BY updated DESC LIMIT 1", (user or profiles.active(),),
        ).fetchone()
    return dict(row) if row else None


def update(goal_id: str, status: str | None = None, note: str | None = None,
           user: str | None = None) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM goals WHERE id = ? AND user_id = ?",
            (goal_id, user or profiles.active()),
        ).fetchone()
        if not row:
            return None
        notes = json.loads(row["notes"] or "[]")
        if note:
            notes.append(note[:220])
        conn.execute(
            "UPDATE goals SET status = ?, notes = ?, updated = ? WHERE id = ? AND user_id = ?",
            (status or row["status"], json.dumps(notes[-30:]), int(time.time()),
             goal_id, user or profiles.active()),
        )
        fresh = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return dict(fresh)


def finish(goal_id: str, user: str | None = None) -> dict | None:
    return update(goal_id, "done", "goal completed", user)


def list_all(user: str | None = None, limit: int = 20) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM goals WHERE user_id = ? ORDER BY updated DESC LIMIT ?",
            (user or profiles.active(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def block(user: str | None = None) -> str:
    goal = current(user)
    if not goal:
        return ""
    notes = json.loads(goal["notes"] or "[]")
    done = "\n".join(f"- {n}" for n in notes[-6:]) or "- (no progress recorded yet)"
    return (
        f"GOAL: {goal['text']}\n"
        f"STATUS: {goal['status']}\n"
        f"PROGRESS SO FAR:\n{done}\n"
        "Keep working toward this goal with tools. "
        "When it is achieved, say GOAL COMPLETE and stop."
    )
