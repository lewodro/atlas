"""Real artifacts: files Atlas actually created or worked on.

Not every temp file is an artifact. Only explicit registrations from a tool or
the user become artifacts. Nothing leaves this machine.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path

import config
import fstools
import profiles

DB = config.ROOT_DATA / "atlas.db"
MAX_PREVIEW = 20000
TEXT_KINDS = {"text", "markdown", "code", "json", "patch"}


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS artifacts (
               id       TEXT PRIMARY KEY,
               title    TEXT NOT NULL,
               kind     TEXT NOT NULL,
               path     TEXT,
               preview  TEXT,
               chat_id  TEXT,
               user_id  TEXT,
               created  INTEGER NOT NULL
           )"""
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(artifacts)")}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE artifacts ADD COLUMN user_id TEXT DEFAULT 'default'")
    return conn


def register(
    title: str,
    kind: str = "file",
    path: str | None = None,
    content: str | None = None,
    chat_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    artifact_id = "a-" + uuid.uuid4().hex[:8]
    preview = ""
    if content and kind.lower() in TEXT_KINDS:
        preview = content[:MAX_PREVIEW]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO artifacts (id, title, kind, path, preview, chat_id, user_id, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (artifact_id, str(title)[:120], kind, path, preview, chat_id,
             user_id or profiles.active(), int(time.time())),
        )
    return get(artifact_id)


def get(artifact_id: str, user_id: str | None = None) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM artifacts WHERE id = ? AND user_id = ?",
            (artifact_id, user_id or profiles.active()),
        ).fetchone()
    return dict(row) if row else None


def list_all(limit: int = 100, user_id: str | None = None) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE user_id = ? ORDER BY created DESC LIMIT ?",
            (user_id or profiles.active(), limit),
        ).fetchall()
    return [dict(row) for row in rows]


def delete(artifact_id: str, user_id: str | None = None) -> bool:
    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM artifacts WHERE id = ? AND user_id = ?",
            (artifact_id, user_id or profiles.active()),
        )
    return bool(cursor.rowcount)


def content_path(artifact_id: str) -> Path | None:
    artifact = get(artifact_id)
    if not artifact or not artifact.get("path"):
        return None
    try:
        path = fstools._safe_path(str(artifact["path"]))
    except fstools.ToolError:
        return None
    return path if path.is_file() else None
