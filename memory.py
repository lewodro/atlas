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

import profiles
from config import API_KEY, BASE_URL, ROOT_DATA, ROOT_NOTES

DB_PATH = ROOT_DATA / "atlas.db"
NOTES = ROOT_NOTES
EMBED_CACHE = ROOT_DATA / "embeddings.json"
EMBED_MODEL = os.getenv("ATLAS_EMBED_MODEL", "nomic-embed-text")
NOTES.mkdir(parents=True, exist_ok=True)
ROOT_DATA.mkdir(parents=True, exist_ok=True)


def notes_root() -> Path:
    """The active profile's Markdown vault. Default keeps the original folder;
    every other profile gets its own isolated directory."""
    user = profiles.active()
    root = NOTES if user == "default" else NOTES / "_profiles" / user
    root.mkdir(parents=True, exist_ok=True)
    return root

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
            user_id TEXT NOT NULL DEFAULT 'default',
            ts      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def log_turn(role: str, content: str, mode: str = "coach", session_id: str = "cli") -> None:
    with _conn() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                   id TEXT PRIMARY KEY, title TEXT DEFAULT 'new chat',
                   mode TEXT DEFAULT 'coach', created TEXT DEFAULT (datetime('now')),
                   updated TEXT DEFAULT (datetime('now')), model TEXT,
                   user_id TEXT DEFAULT 'default')"""
        )
        row = conn.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            user = profiles.active()
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, title, mode, user_id) VALUES (?, ?, ?, ?)",
                (session_id, "terminal", "coach", user),
            )
        else:
            user = row[0]
        conn.execute(
            "INSERT INTO turns (mode, role, content, session_id, user_id) VALUES (?, ?, ?, ?, ?)",
            (mode, role, content, session_id, user),
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


def cli_session() -> str:
    """The permanent terminal chat, scoped to the active profile."""
    user = profiles.active()
    sid = CLI_SESSION if user == "default" else f"cli:{user}"
    conn = _conn()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, mode, user_id) VALUES (?, ?, ?, ?)",
            (sid, "terminal", "coach", user),
        )
    return sid


def _migrate() -> None:
    """Old databases predate sessions. Upgrade them in place."""
    with _conn() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
        if "session_id" not in cols:
            conn.execute("ALTER TABLE turns ADD COLUMN session_id TEXT DEFAULT 'cli'")
        if "user_id" not in cols:
            conn.execute("ALTER TABLE turns ADD COLUMN user_id TEXT DEFAULT 'default'")
        conn.execute("CREATE INDEX IF NOT EXISTS turns_user ON turns(user_id, session_id)")
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
        if "user_id" not in session_cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_id TEXT DEFAULT 'default'")
        conn.execute("CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)")
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, mode) VALUES (?, ?, ?)",
            (CLI_SESSION, "terminal", "coach"),
        )


def list_sessions(user_id: str | None = None) -> list[dict]:
    user = user_id or profiles.active()
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.mode, s.created, s.updated, s.model,
                   (SELECT COUNT(*) FROM turns t
                     WHERE t.session_id = s.id AND t.role IN ('user','assistant')) AS n
            FROM sessions s
            WHERE s.user_id = ?
            ORDER BY s.updated DESC
            """, (user,)
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
    mode: str = "coach", title: str = "new chat", model: str | None = None,
    user_id: str | None = None,
) -> str:
    sid = dt.datetime.now().strftime("%y%m%d-%H%M%S-") + os.urandom(2).hex()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (id, title, mode, model, user_id) VALUES (?, ?, ?, ?, ?)",
            (sid, title, mode, model, user_id or profiles.active()),
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
            conn.execute("UPDATE sessions SET title = ? WHERE id = ? AND user_id = ?", (title[:80], session_id, profiles.active()))
        if mode is not None:
            conn.execute("UPDATE sessions SET mode = ? WHERE id = ? AND user_id = ?", (mode, session_id, profiles.active()))
        if model is not None:
            conn.execute("UPDATE sessions SET model = ? WHERE id = ? AND user_id = ?", (model or None, session_id, profiles.active()))
        conn.execute("UPDATE sessions SET updated = datetime('now') WHERE id = ?", (session_id,))


def delete_session(session_id: str) -> None:
    if session_id in (CLI_SESSION, cli_session()):
        raise ValueError("the terminal session is permanent")
    user = profiles.active()
    with _conn() as conn:
        conn.execute("DELETE FROM turns WHERE session_id = ? AND user_id = ?", (session_id, user))
        conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user))


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
        return conn.execute(
            "SELECT 1 FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, profiles.active()),
        ).fetchone() is not None


def stats() -> dict:
    with _conn() as conn:
        turns = conn.execute(
            "SELECT COUNT(*) FROM turns WHERE role IN ('user','assistant') AND user_id = ?",
            (profiles.active(),),
        ).fetchone()[0]
        sessions = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (profiles.active(),)
        ).fetchone()[0]
    return {"turns": turns, "sessions": sessions, "notes": len(note_paths())}


# ---------------------------------------------------------------- notes

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = set(
    "the a an is are was were user i my me we our you your it its of to in on at "
    "for and or that this these those be been has have had do does did as with "
    "im about how what why when who where can could should would will "
    "have has had much many work works working worked make makes made use "
    "used uses using want wants need needs like get gets got thing things "
    "really very also even still know think help".split()
)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _stem(word: str) -> str:
    """Tiny suffix stripper. 'programming'/'programmer' -> 'programm'.

    Enough to keep the offline keyword fallback useful when no embedding
    model is running — which is exactly when you need it most.
    """
    if len(word) > 5 and word.endswith("ying"):
        return word[:-4] + "y"  # studying -> study
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"  # studies -> study
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith(("ed", "er")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def keywords(text: str) -> set[str]:
    """Meaningful, lightly stemmed words, so 'write' matches 'writes'."""
    return {_stem(word) for word in _words(text) - _STOP}


def _category(path: Path) -> str:
    match = re.search(r"(?m)^category:\s*([a-z0-9-]+)", path.read_text(
        encoding="utf-8", errors="ignore"
    )[:400])
    return match.group(1) if match else ""


def _body(path: Path) -> str:
    """Note body plus its tags/category — both are retrieval signals."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    parts = text.split("---", 2)
    if len(parts) != 3:
        return text.strip()
    tags = [
        line.strip()
        for line in parts[1].splitlines()
        if line.strip().startswith(("tags:", "category:"))
    ]
    return (parts[2].strip() + "\n" + "\n".join(tags)).strip()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48] or "note").strip("-")


def find_note(text: str) -> Path | None:
    """An existing note that says roughly the same thing."""
    target = keywords(text)
    if not target:
        return None
    for path in notes_root().glob("*.md"):
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
    path = notes_root() / f"{stamp}-{_slug(text)}.md"
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
    return sorted(p for p in notes_root().glob("*.md") if not p.name.startswith("_"))


def recall(query: str, k: int = 5, budget: int = 2600) -> str:
    """Find the notes that matter for this question.

    Two strategies, in order:
      1. embeddings (semantic: "studying" matches "learning") if available
      2. keywords (dumb, transparent, works offline forever)
      3. the newest notes, so "what do you know about me?" is never empty
    """
    # Both channels run, then they vote. Previously a single weak keyword hit
    # ("language") suppressed semantic recall entirely, so "which language do
    # I write" returned an unrelated note about TEST SOL. Merging fixed that.
    strategy = os.getenv("ATLAS_RETRIEVAL", "hybrid").lower()

    keyword = [] if strategy == "semantic" else _keyword_hits(query)
    # Keywords are free and usually enough. Only pay for an embedding call
    # when they find nothing — e.g. "studying" vs "learning".
    semantic = []
    if strategy != "keyword" and not keyword:
        semantic = _semantic_hits(query)
    hits = rank_hits(keyword, semantic)
    if not hits:
        # rank_hits() returns (Path, score); keep that order or recall() will
        # try to read() a float and crash on every no-match question.
        hits = [(p, 0.0) for p in _recent(3)]

    chunks, used = [], 0
    for path, _ in hits[:k]:
        body = _body(path)
        if used + len(body) > budget:
            body = body[: max(0, budget - used)] + "…"
        chunks.append(f"[{path.stem}]\n{body}")
        used += len(body)
        if used >= budget:
            break
    structured = profiles.context_block(profiles.active(), query, k=5)
    if structured:
        # Structured facts are already compact. Keep the raw note supplement
        # small so a 2B model does not drown in context.
        return structured + "\n\n" + "\n\n".join(chunks[:2])[:1200]
    return "\n\n".join(chunks)


def rank_hits(
    keyword: list[tuple[float, Path]], semantic: list[tuple[float, Path]]
) -> list[tuple[Path, float]]:
    """Keyword and semantic scores vote together; a weak keyword hit must
    never hide a strong semantic one (the 2026-11 retrieval bug)."""
    scores: dict[Path, float] = {}
    for score, path in keyword:
        scores[path] = scores.get(path, 0.0) + score
    for score, path in semantic:
        scores[path] = scores.get(path, 0.0) + 2.0 * score
    return sorted(scores.items(), key=lambda row: (-row[1], -row[0].stat().st_mtime))


def _recent(n: int) -> list[Path]:
    return sorted(note_paths(), key=lambda p: -p.stat().st_mtime)[:n]


def _keyword_hits(query: str) -> list[tuple[float, Path]]:
    # Intent words are not facts, but they point at the right note category.
    intent = ""
    lowered = query.lower()
    if "who am i" in lowered or "about me" in lowered or "my name" in lowered:
        intent = " identity name born student "
    elif "how do i prefer" in lowered or "how do i like" in lowered:
        intent = " preferences "
    wanted = keywords(intent + query)
    if not wanted:
        return []
    hits = []
    for path in note_paths():
        other = keywords(_body(path))
        found = set()
        for word in wanted:
            if word in other:
                found.add(word)
            elif any(
                candidate.startswith(word) or word.startswith(candidate)
                for candidate in other
                if min(len(candidate), len(word)) >= 3
            ):
                found.add(word)  # "mac" matches "macbook"
        if found:
            score = len(found) / (len(wanted) ** 0.5)
            if _category(path) in wanted:
                score += 0.6  # a note filed under this exact topic wins
            hits.append((score, path))
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
                scored.append((score, Path(name)))
        scored.sort(key=lambda row: -row[0])
        return scored
    except Exception:
        return []  # no model, no network, no problem: keywords still work


def _normalise(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def _embed(texts: list[str]) -> list[list[float]]:
    import models
    from openai import OpenAI

    current = models.load()
    client = OpenAI(base_url=current["base_url"], api_key=current["api_key"])
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
        key = str(path)
        entry = cache.get(key)
        if entry and abs(entry["mtime"] - mtime) < 1:
            vectors[key] = _normalise(np.array(entry["vec"], dtype=np.float32))
        else:
            stale.append(path)

    if stale:
        fresh = _embed([_body(p) for p in stale])
        for path, vec in zip(stale, fresh):
            key = str(path)
            vectors[key] = _normalise(np.array(vec, dtype=np.float32))
            cache[key] = {"mtime": path.stat().st_mtime, "vec": vec}
        keep = {str(p) for p in note_paths()}
        cache = {k: v for k, v in cache.items() if k in keep}
        EMBED_CACHE.parent.mkdir(parents=True, exist_ok=True)
        EMBED_CACHE.write_text(json.dumps(cache))

    return vectors


def digest(max_chars: int = 1200) -> str:
    path = notes_root() / DIGEST_NAME
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
        print(f"vault : {notes_root()}")
    elif len(sys.argv) > 1:
        print(recall(" ".join(sys.argv[1:])) or "(no matches)")
    else:
        print("usage: python memory.py --stats | python memory.py <query>")
