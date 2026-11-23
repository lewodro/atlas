"""Per-user profiles and structured, local-only memory.

Atlas's existing SQLite database holds conversations (sessions/turns); this
module adds the identity layer around it. All reads and writes are conditioned
on an application-managed user id, so switching models never changes memory
and two profiles cannot see each other's facts even on the same model.

Schema lives in the same data/atlas.db. FTS5 is used when available, with a
pure-Python keyword fallback. Nothing here calls the network.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from pathlib import Path

from config import ROOT_DATA

DB = ROOT_DATA / "atlas.db"
DB.parent.mkdir(parents=True, exist_ok=True)
ACTIVE_FILE = ROOT_DATA / "profile.json"
DEFAULT = "default"

CATEGORIES = {
    "identity", "preferences", "education", "projects", "goals",
    "decisions", "temporary", "communication", "learning", "health",
    # seed-specific categories preserved from the imported profile
    "programming", "dev-interests", "last-seat", "atlas", "games-renderer",
    "tennis", "tennis-goals", "ambitions", "audio", "memory-rules",
}

#: Private backup format written by `atlas memory export FILE`. A file is just
#: JSON you can copy between machines — nothing is uploaded, no GitHub needed.
FORMAT = "atlas-memory"
VERSION = 1

# Generic question → category hints. No personal data lives here.
HINTS = {
    "study": "education", "studies": "education", "studying": "education", "student": "education",
    "university": "education", "course": "education", "degree": "education",
    "learn": "learning", "learning": "learning", "prefer": "learning",
    "project": "projects", "projects": "projects", "building": "projects",
    "sport": "tennis", "sports": "tennis", "tennis": "tennis",
    "goal": "goals", "goals": "goals", "remember": "identity",
}

SENSITIVE = re.compile(
    r"(sk-[a-z0-9]{8,}|ghp_[a-z0-9]{8,}|api[_ -]?key\s*[:=]|password\s*[:=]|"
    r"bearer\s+[a-z0-9._-]{8,}|-----begin .*private key-----|\.env\b)",
    re.IGNORECASE,
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _fts() -> bool:
    try:
        with _conn() as conn:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            conn.execute("DROP TABLE _fts_probe")
        return True
    except sqlite3.Error:
        return False


HAS_FTS = _fts()


def migrate() -> None:
    with _conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS profiles (
                   id      TEXT PRIMARY KEY,
                   name    TEXT NOT NULL,
                   created TEXT NOT NULL DEFAULT (datetime('now'))
               )"""
        )
        conn.execute(
            "INSERT OR IGNORE INTO profiles (id, name) VALUES (?, ?)",
            (DEFAULT, "Personal (default)"),
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS memories (
                   id          INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id     TEXT NOT NULL,
                   category    TEXT NOT NULL,
                   content     TEXT NOT NULL,
                   source      TEXT NOT NULL DEFAULT 'user',
                   created     TEXT NOT NULL DEFAULT (datetime('now')),
                   updated     TEXT NOT NULL DEFAULT (datetime('now')),
                   confidence  REAL NOT NULL DEFAULT 0.8,
                   importance  REAL NOT NULL DEFAULT 0.5,
                   expires     TEXT
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS memories_user ON memories(user_id, category)"
        )
        if HAS_FTS:
            conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                   USING fts5(content, category, tokenize='unicode61')"""
            )


migrate()


# ---------------------------------------------------------------- profiles

def active() -> str:
    if ACTIVE_FILE.exists():
        try:
            current = json.loads(ACTIVE_FILE.read_text()).get("active", DEFAULT)
        except (json.JSONDecodeError, OSError):
            current = DEFAULT
    else:
        current = DEFAULT
    with _conn() as conn:
        exists = conn.execute("SELECT 1 FROM profiles WHERE id = ?", (current,)).fetchone()
    return current if exists else DEFAULT


def switch(profile_id: str) -> str:
    with _conn() as conn:
        found = conn.execute(
            "SELECT 1 FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    if not found:
        raise ValueError(f"unknown profile {profile_id!r}")
    ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(json.dumps({"active": profile_id}, indent=2) + "\n")
    return profile_id


def create(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("profile needs a name")
    profile_id = "u-" + uuid.uuid4().hex[:8]
    with _conn() as conn:
        conn.execute(
            "INSERT INTO profiles (id, name) VALUES (?, ?)", (profile_id, name)
        )
    return profile_id


def list_profiles() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name, p.created,
                      (SELECT COUNT(*) FROM memories m WHERE m.user_id = p.id) AS memories
               FROM profiles p ORDER BY p.created, p.id"""
        ).fetchall()
    current = active()
    return [{**dict(r), "active": r["id"] == current} for r in rows]


def rename(profile_id: str, name: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE profiles SET name = ? WHERE id = ?", (name.strip(), profile_id))


# ---------------------------------------------------------------- memories

def infer_category(text: str) -> str:
    low = text.lower()
    if any(word in low for word in ("temporary", "test project", "codename", "right now", "this week")):
        return "temporary"
    if any(word in low for word in ("project", "last seat", "atlas", "building", "repo")):
        return "projects"
    if any(word in low for word in ("learn", "study", "prefer", "explain", "teach")):
        return "learning"
    if any(word in low for word in ("goal", "want to become", "plan to")):
        return "goals"
    return "identity"


def _safe(content: str) -> str:
    if SENSITIVE.search(content):
        raise ValueError("refusing to store a secret (key, password, token or .env)")
    return content.strip()


def _sync_fts(conn: sqlite3.Connection, row_id: int, content: str, category: str) -> None:
    if not HAS_FTS:
        return
    conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (row_id,))
    conn.execute(
        "INSERT INTO memories_fts (rowid, content, category) VALUES (?, ?, ?)",
        (row_id, content, category),
    )


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def add(
    user: str,
    category: str,
    content: str,
    source: str = "user",
    confidence: float = 0.7,
    importance: float = 0.5,
    expires: str | None = None,
    created: str | None = None,
) -> tuple[int, str]:
    """Insert, dedupe, or reconcile a memory. Returns (id, status)."""
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; use one of {sorted(CATEGORIES)}")
    content = _safe(content)
    if not content:
        raise ValueError("empty memory")

    with _conn() as conn:
        existing = conn.execute(
            "SELECT * FROM memories WHERE user_id = ? AND category = ?",
            (user, category),
        ).fetchall()
        wanted = _words(content)
        for row in existing:
            have = _words(row["content"])
            if not wanted or not have:
                continue
            overlap = len(wanted & have) / len(wanted | have)
            if overlap >= 0.95:  # same fact, different phrasing → keep one
                return row["id"], "known"
            if overlap >= 0.6:  # a correction of the same fact
                conn.execute(
                    """UPDATE memories SET content = ?, source = ?, confidence = ?,
                       importance = ?, expires = ?, updated = datetime('now')
                       WHERE id = ?""",
                    (content, source, confidence, importance, expires, row["id"]),
                )
                _sync_fts(conn, row["id"], content, category)
                return row["id"], "updated"

        columns = "user_id, category, content, source, confidence, importance, expires"
        values = "?, ?, ?, ?, ?, ?, ?"
        params = [user, category, content, source, confidence, importance, expires]
        if created:
            columns += ", created"
            values += ", ?"
            params.append(created)
        cursor = conn.execute(
            f"INSERT INTO memories ({columns}) VALUES ({values})", params
        )
        row_id = cursor.lastrowid
        _sync_fts(conn, row_id, content, category)
    return row_id, "saved"


def search(user: str, query: str, k: int = 6) -> list[dict]:
    """FTS-ranked, user-scoped retrieval with a keyword fallback."""
    with _conn() as conn:
        tokens: list[str] = []
        rows = []
        if HAS_FTS:
            stopped = {"who", "what", "the", "and", "for", "with", "tell", "please",
                       "your", "from", "this", "that", "about", "have", "does"}
            tokens = [t for t in re.findall(r"[a-zA-Z0-9]{2,}", query.lower())
                      if t not in stopped]
            low = query.lower()
            if any(key in low for key in ("who am i", "who i am", "my name", "tell me who")):
                tokens += ["identity", "education", "tennis", "projects"]
            for token in list(tokens):
                hint = HINTS.get(token)
                if hint and hint not in tokens:
                    tokens.append(hint)
            # Prefix matching handles study/studies/studying and project/projects.
            match = " OR ".join(t + "*" for t in tokens)
            if match:
                try:
                    rows = conn.execute(
                        """SELECT m.* FROM memories_fts f
                           JOIN memories m ON m.id = f.rowid
                           WHERE memories_fts MATCH ? AND m.user_id = ?
                           ORDER BY bm25(memories_fts) LIMIT ?""",
                        (match, user, k * 3),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
        if not rows:
            wanted = _words(query)
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id = ?", (user,)
            ).fetchall()
            rows = [r for r in rows if wanted & (_words(r["content"]) | _words(r["category"]))]

        now = time.time()
        scored = []
        for row in rows:
            if row["expires"] and row["expires"] < time.strftime("%Y-%m-%d"):
                continue
            age = time.time() - (
                time.mktime(time.strptime(row["updated"][:10], "%Y-%m-%d"))
                if row["updated"] else now
            )
            recency = max(0.0, 1.0 - age / (365 * 86400))
            score = row["confidence"] + row["importance"] + recency
            haystack = (row["content"] + " " + row["category"]).lower()
            words = re.findall(r"[a-z0-9]{3,}", haystack)
            overlaps = sum(
                1 for token in tokens
                if token in words or any(w.startswith(token) for w in words)
            )
            score += min(1.2, 0.2 * overlaps)
            if row["category"] in tokens:
                score += 0.8
            scored.append((score, dict(row)))
        scored.sort(key=lambda item: -item[0])
    return [row for _, row in scored[:k]]


def context_block(user: str, query: str, k: int = 4) -> str:
    hits = search(user, query, k)
    if not hits:
        return ""
    lines = [f"SAVED MEMORY [{h['category']}]: {h['content']}" for h in hits]
    return "\n".join(lines)


def list_all(user: str, category: str | None = None) -> list[dict]:
    with _conn() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id = ? AND category = ? ORDER BY updated DESC",
                (user, category),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id = ? ORDER BY updated DESC", (user,)
            ).fetchall()
    return [dict(r) for r in rows]


def get(memory_id: int, user: str | None = None) -> dict | None:
    with _conn() as conn:
        if user:
            row = conn.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ?", (memory_id, user)
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return dict(row) if row else None


def update(memory_id: int, user: str, content: str | None = None, **fields) -> dict:
    """Explicit correction. Scoped by user id at the SQL layer."""
    current = get(memory_id, user)
    if not current:
        raise ValueError("no such memory for this profile")
    content = _safe(content) if content is not None else current["content"]
    allowed = {"category", "source", "confidence", "importance", "expires"}
    sets, values = ["content = ?", "updated = datetime('now')"], [content]
    for key, value in fields.items():
        if key in allowed and value is not None:
            sets.append(f"{key} = ?")
            values.append(value)
    values.append(memory_id)
    values.append(user)
    with _conn() as conn:
        conn.execute(
            f"UPDATE memories SET {', '.join(sets)} WHERE id = ? AND user_id = ?", values
        )
        _sync_fts(conn, memory_id, content, fields.get("category", current["category"]))
    return get(memory_id, user)


def forget(memory_id: int, user: str) -> bool:
    with _conn() as conn:
        cursor = conn.execute(
            "DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user)
        )
        if cursor.rowcount and HAS_FTS:
            conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
    return bool(cursor.rowcount)


def export(user: str) -> dict:
    """A versioned, private backup of one profile's durable memories."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT id, name FROM profiles WHERE id = ?", (user,)
        ).fetchone()
    profile = {"id": user, "name": row["name"] if row else user}
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "profile": profile,
        "memories": list_all(user),
    }


def _number(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def import_data(payload: dict, user: str | None = None) -> dict:
    """Import a backup. Validates, preserves ids/categories, never duplicates.

    Accepts the current `atlas memory export` format and the older bare
    ``{"profile": "...", "memories": [...]}`` shape. Returns counts for a
    clear CLI report. Two backups imported twice produce no extra rows.
    """
    if not isinstance(payload, dict):
        raise ValueError("memory file must contain a JSON object")
    fmt = payload.get("format")
    if fmt is not None and fmt != FORMAT:
        raise ValueError(f"unsupported memory format {fmt!r}; expected {FORMAT!r}")
    version = _number(payload.get("version", VERSION), -1)
    if version < 1:
        raise ValueError(f"invalid memory file version {payload.get('version')!r}")
    if version > VERSION:
        raise ValueError(
            f"memory file version {int(version)} is newer than this Atlas "
            f"(supports up to {VERSION}) — update Atlas first"
        )
    items = payload.get("memories")
    if not isinstance(items, list):
        raise ValueError("memory file is missing a 'memories' list")

    profile = payload.get("profile") or {}
    if isinstance(profile, str):  # legacy export stored just the profile id
        profile = {"id": profile}
    if not isinstance(profile, dict):
        raise ValueError("memory file has an invalid 'profile' field")
    target = str(user or profile.get("id") or active()).strip() or DEFAULT
    name = str(profile.get("name") or target)

    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO profiles (id, name) VALUES (?, ?)",
            (target, name),
        )
        known_ids = {row[0] for row in conn.execute("SELECT id FROM memories")}
        existing = [
            (row["id"], _words(row["content"]))
            for row in conn.execute(
                "SELECT id, content FROM memories WHERE user_id = ?", (target,)
            )
        ]

    counts = {"imported": 0, "duplicates": 0, "skipped": 0}
    for item in items:
        if not isinstance(item, dict):
            counts["skipped"] += 1
            continue
        content = str(item.get("content") or "").strip()
        category = str(item.get("category") or "identity").strip() or "identity"
        if not content:
            counts["skipped"] += 1
            continue
        try:
            content = _safe(content)  # never import a secret from a backup
        except ValueError:
            counts["skipped"] += 1
            continue

        raw_id = item.get("id")
        try:
            memory_id = int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            memory_id = None
        if memory_id is not None and memory_id in known_ids:
            # The id already exists elsewhere in this database (e.g. importing
            # into a second profile on the same machine). Keep the content and
            # category; let SQLite assign a fresh id. Content dedupe below still
            # prevents true duplicates within the target profile.
            memory_id = None

        wanted = _words(content)
        if any(
            not wanted or not have or len(wanted & have) / len(wanted | have) >= 0.95
            for _, have in existing
        ):
            counts["duplicates"] += 1
            continue

        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        columns = [
            "user_id", "category", "content", "source", "confidence",
            "importance", "expires", "created", "updated",
        ]
        values = [
            target, category, content, str(item.get("source") or "import"),
            _number(item.get("confidence"), 0.8),
            _number(item.get("importance"), 0.5),
            item.get("expires"), item.get("created") or stamp,
            item.get("updated") or stamp,
        ]
        if memory_id is not None:
            columns.insert(0, "id")
            values.insert(0, memory_id)
        try:
            with _conn() as conn:
                cursor = conn.execute(
                    f"INSERT INTO memories ({', '.join(columns)}) "
                    f"VALUES ({', '.join('?' for _ in values)})",
                    values,
                )
                new_id = cursor.lastrowid
                _sync_fts(conn, new_id, content, category)
        except sqlite3.IntegrityError:
            counts["skipped"] += 1  # id collided with another profile's row
            continue
        known_ids.add(new_id)
        existing.append((new_id, wanted))
        counts["imported"] += 1

    return {"profile": target, **counts}


def clear(user: str) -> int:
    with _conn() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM memories WHERE user_id = ?", (user,)
        )]
        conn.execute("DELETE FROM memories WHERE user_id = ?", (user,))
        if HAS_FTS:
            for memory_id in ids:
                conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (memory_id,))
    return len(ids)
