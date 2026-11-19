"""Memory: the part that makes the mentor outlive the chat.

  data/atlas.db  - every turn, append-only. Raw history.
  notes/         - one Markdown file per fact. Human-readable, editable.
  notes/_*.md    - GENERATED files (digest, reflection). Never retrieved.

    uv run python memory.py --stats
    uv run python memory.py git
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
from pathlib import Path

import numpy as np

from config import API_KEY, BASE_URL, ROOT_DATA, ROOT_NOTES

DB_PATH = ROOT_DATA / "atlas.db"
NOTES = ROOT_NOTES
EMBED_CACHE = ROOT_DATA / "embeddings.json"
EMBED_MODEL = os.getenv("ATLAS_EMBED_MODEL", "nomic-embed-text")
NOTES.mkdir(parents=True, exist_ok=True)
ROOT_DATA.mkdir(parents=True, exist_ok=True)

DIGEST_NAME = "_digest.md"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            mode    TEXT NOT NULL DEFAULT 'coach',
            role    TEXT NOT NULL,
            content TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT 'cli',
            ts      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def log_turn(role: str, content: str, mode: str = "coach", session_id: str = "cli") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO turns (mode, role, content, session_id) VALUES (?, ?, ?, ?)",
            (mode, role, content, session_id),
        )


def load_recent(n: int = 16, session_id: str = "cli") -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM turns "
            "WHERE role IN ('user', 'assistant') AND session_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (session_id, n),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


# ---------------------------------------------------------------- sessions

CLI_SESSION = "cli"


def _migrate() -> None:
    """Old databases predate sessions. Upgrade them in place."""
    with _conn() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
        if "session_id" not in cols:
            conn.execute("ALTER TABLE turns ADD COLUMN session_id TEXT DEFAULT 'cli'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id      TEXT PRIMARY KEY,
                title   TEXT NOT NULL DEFAULT 'new chat',
                mode    TEXT NOT NULL DEFAULT 'coach',
                created TEXT NOT NULL DEFAULT (datetime('now')),
                updated TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        session_cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "model" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN model TEXT")
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, mode) VALUES (?, ?, ?)",
            (CLI_SESSION, "terminal", "coach"),
        )


def list_sessions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.mode, s.created, s.updated, s.model,
                   (SELECT COUNT(*) FROM turns t
                     WHERE t.session_id = s.id AND t.role IN ('user','assistant')) AS n
            FROM sessions s
            ORDER BY s.updated DESC
            """
        ).fetchall()
    return [
        {
            "id": r[0], "title": r[1], "mode": r[2], "created": r[3],
            "updated": r[4], "model": r[5], "turns": r[6],
        }
        for r in rows
    ]


def get_session(session_id: str) -> dict | None:
    return next((s for s in list_sessions() if s["id"] == session_id), None)


def create_session(
    mode: str = "coach", title: str = "new chat", model: str | None = None
) -> str:
    sid = dt.datetime.now().strftime("%y%m%d-%H%M%S-") + os.urandom(2).hex()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, mode, model) VALUES (?, ?, ?, ?)",
            (sid, title, mode, model),
        )
    return sid


def update_session(
    session_id: str,
    title: str | None = None,
    mode: str | None = None,
    model: str | None = None,
) -> None:
    with _conn() as conn:
        if title is not None:
            conn.execute("UPDATE sessions SET title = ? WHERE id = ?", (title[:80], session_id))
        if mode is not None:
            conn.execute("UPDATE sessions SET mode = ? WHERE id = ?", (mode, session_id))
        if model is not None:
            conn.execute("UPDATE sessions SET model = ? WHERE id = ?", (model or None, session_id))
        conn.execute("UPDATE sessions SET updated = datetime('now') WHERE id = ?", (session_id,))


def delete_session(session_id: str) -> None:
    if session_id == CLI_SESSION:
        raise ValueError("the terminal session is permanent")
    with _conn() as conn:
        conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def session_messages(session_id: str) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content, ts FROM turns "
            "WHERE session_id = ? AND role IN ('user','assistant') ORDER BY id",
            (session_id,),
        ).fetchall()
    return [{"role": r, "content": c, "ts": ts} for r, c, ts in rows]


def session_exists(session_id: str) -> bool:
    with _conn() as conn:
        return conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone() is not None


def stats() -> dict:
    with _conn() as conn:
        turns = conn.execute(
            "SELECT COUNT(*) FROM turns WHERE role IN ('user','assistant')"
        ).fetchone()[0]
        sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    return {"turns": turns, "sessions": sessions, "notes": len(note_paths())}


# ---------------------------------------------------------------- notes

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = set(
    "the a an is are was were user i my me we our you your it its of to in on at "
    "for and or that this these those be been has have had do does did as with "
    "im about how what why when who where can could should would will".split()
)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def keywords(text: str) -> set[str]:
    """Meaningful words only, so 'I am learning Python' matches
    'The user is learning Python'."""
    return _words(text) - _STOP


def _body(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text.split("---", 2)[-1].strip()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48] or "note").strip("-")


def find_note(text: str) -> Path | None:
    """An existing note that says roughly the same thing."""
    target = keywords(text)
    if not target:
        return None
    for path in NOTES.glob("*.md"):
        if path.name.startswith("_"):
            continue
        other = keywords(_body(path))
        if len(target & other) < 3:
            continue
        if len(target & other) / len(target | other) >= 0.6:
            return path
    return None


def remember(text: str, tags: list[str] | None = None) -> Path:
    text = text.strip()
    if not text:
        raise ValueError("refusing to save an empty note")

    existing = find_note(text)
    if existing:
        return existing

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = NOTES / f"{stamp}-{_slug(text)}.md"
    clean_tags = [
        t.strip().replace("]", "").replace("[", "")
        for t in (tags or [])
        if t.strip()
    ]
    tag_line = ", ".join(clean_tags)
    path.write_text(
        f"---\ncreated: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"updated: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"type: atlas-memory\ntags: [{tag_line}]\n---\n\n{text}\n",
        encoding="utf-8",
    )
    log_turn("memory", f"saved {path.name}")
    return path


def update_note(ref: str, text: str, tags: list[str] | None = None) -> Path:
    """Replace one known memory by exact filename or stem.

    Exact matching matters: a model may suggest the edit, but it never gets a
    fuzzy delete/overwrite primitive.
    """
    text = text.strip()
    if not text:
        raise ValueError("refusing to save an empty note")
    path = next(
        (p for p in note_paths() if ref.strip() in {p.name, p.stem}),
        None,
    )
    if path is None:
        raise ValueError(f"no memory named {ref!r}")

    old = path.read_text(encoding="utf-8", errors="ignore")
    created = re.search(r"(?m)^created:\s*(.+)$", old)
    created_value = (
        created.group(1).strip()
        if created
        else dt.datetime.now().isoformat(timespec="seconds")
    )
    old_tags = re.search(r"(?m)^tags:\s*(.+)$", old)
    clean_tags = [
        t.strip().replace("]", "").replace("[", "")
        for t in (tags or [])
        if t.strip()
    ]
    tag_value = f"[{', '.join(clean_tags)}]" if clean_tags else (
        old_tags.group(1).strip() if old_tags else "[]"
    )
    path.write_text(
        f"---\ncreated: {created_value}\n"
        f"updated: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"type: atlas-memory\ntags: {tag_value}\n---\n\n{text}\n",
        encoding="utf-8",
    )
    log_turn("memory", f"updated {path.name}")
    return path


def note_paths() -> list[Path]:
    """Real notes only: files starting with '_' are generated."""
    return sorted(p for p in NOTES.glob("*.md") if not p.name.startswith("_"))


def recall(query: str, k: int = 5, budget: int = 2600) -> str:
    """Find the notes that matter for this question.

    Two strategies, in order:
      1. embeddings (semantic: "studying" matches "learning") if available
      2. keywords (dumb, transparent, works offline forever)
      3. the newest notes, so "what do you know about me?" is never empty
    """
    # Exact keyword recall is effectively free and avoids loading/running a
    # second model before every chat response. Semantic recall remains the
    # fallback when wording differs ("studying" vs "learning").
    wanted = keywords(query)
    strategy = os.getenv("ATLAS_RETRIEVAL", "hybrid").lower()
    if strategy == "semantic":
        hits = _semantic_hits(query)
    else:
        hits = _keyword_hits(query)
        if not hits and wanted and strategy != "keyword":
            hits = _semantic_hits(query)
    if not hits:
        hits = [(0.0, p) for p in _recent(3)]

    chunks, used = [], 0
    for _, path in hits[:k]:
        body = _body(path)
        if used + len(body) > budget:
            body = body[: max(0, budget - used)] + "…"
        chunks.append(f"[{path.stem}]\n{body}")
        used += len(body)
        if used >= budget:
            break
    return "\n\n".join(chunks)


def _recent(n: int) -> list[Path]:
    return sorted(note_paths(), key=lambda p: -p.stat().st_mtime)[:n]


def _keyword_hits(query: str) -> list[tuple[float, Path]]:
    wanted = keywords(query)
    if not wanted:
        return []
    hits = []
    for path in note_paths():
        found = wanted & keywords(_body(path))
        if found:
            hits.append((len(found) / (len(wanted) ** 0.5), path))
    hits.sort(key=lambda row: (-row[0], -row[1].stat().st_mtime))
    return hits


def _semantic_hits(query: str, floor: float = 0.45) -> list[tuple[float, Path]]:
    """Cosine similarity over cached embeddings. Returns [] on any problem."""
    try:
        vectors = _note_vectors()
        if not vectors:
            return []
        q = _normalise(np.array(_embed([query])[0], dtype=np.float32))
        scored = []
        for name, vec in vectors.items():
            score = float(np.dot(q, vec))
            if score >= floor:
                scored.append((score, NOTES / name))
        scored.sort(key=lambda row: -row[0])
        return scored
    except Exception:
        return []  # no model, no network, no problem: keywords still work


def _normalise(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def _embed(texts: list[str]) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    reply = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in reply.data]


def _note_vectors() -> dict[str, np.ndarray]:
    """Embeddings cached in data/embeddings.json, invalidated by mtime."""
    cache: dict = {}
    if EMBED_CACHE.exists():
        try:
            cache = json.loads(EMBED_CACHE.read_text())
        except json.JSONDecodeError:
            cache = {}

    vectors: dict[str, np.ndarray] = {}
    stale: list[Path] = []

    for path in note_paths():
        mtime = path.stat().st_mtime
        entry = cache.get(path.name)
        if entry and abs(entry["mtime"] - mtime) < 1:
            vectors[path.name] = _normalise(np.array(entry["vec"], dtype=np.float32))
        else:
            stale.append(path)

    if stale:
        fresh = _embed([_body(p) for p in stale])
        for path, vec in zip(stale, fresh):
            vectors[path.name] = _normalise(np.array(vec, dtype=np.float32))
            cache[path.name] = {"mtime": path.stat().st_mtime, "vec": vec}
        keep = {p.name for p in note_paths()}
        cache = {k: v for k, v in cache.items() if k in keep}
        EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        EMBED_CACHE.write_text(json.dumps(cache))

    return vectors


def digest(max_chars: int = 1200) -> str:
    path = NOTES / DIGEST_NAME
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]


_migrate()


if __name__ == "__main__":
    import sys

    if "--remember" in sys.argv:
        i = sys.argv.index("--remember")
        text = " ".join(sys.argv[i + 1:]).strip()
        if not text:
            raise SystemExit("usage: atlas remember \"a durable fact about me\"")
        print(remember(text, ["manual"]))
    elif "--stats" in sys.argv:
        with _conn() as conn:
            turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        print(f"turns : {turns}")
        print(f"notes : {len(note_paths())}")
        print(f"db    : {DB_PATH}")
        print(f"vault : {NOTES}")
    elif len(sys.argv) > 1:
        print(recall(" ".join(sys.argv[1:])) or "(no matches)")
    else:
        print("usage: python memory.py --stats | python memory.py <query>")
