<<<<<<< HEAD
"""Memory: the part that makes the mentor outlive the chat.

  data/atlas.db  - every turn, append-only. Raw history.
  notes/         - one Markdown file per fact. Human-readable, editable.
  notes/_*.md    - GENERATED files (digest, reflection). Never retrieved.

    uv run python memory.py --stats
    uv run python memory.py git
=======
"""Memory: the part that makes the brain outlive the chat.

Two stores, deliberately boring:

  1. brain.db  - SQLite log of every turn. Raw history. Never edited.
  2. notes/    - one Markdown file per fact. Human-readable. You can edit it.

The rule of thumb this file follows:
    * files you can open with `cat` beat any database you can't.

Run `python memory.py --stats` at any time to see what's in there.
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
"""

from __future__ import annotations

import datetime as dt
<<<<<<< HEAD
import json
import os
=======
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
import re
import sqlite3
from pathlib import Path

<<<<<<< HEAD
import numpy as np

from config import API_KEY, BASE_URL, ROOT_DATA, ROOT_NOTES

DB_PATH = ROOT_DATA / "atlas.db"
NOTES = ROOT_NOTES
EMBED_CACHE = ROOT_DATA / "embeddings.json"
EMBED_MODEL = os.getenv("ATLAS_EMBED_MODEL", "nomic-embed-text")
NOTES.mkdir(parents=True, exist_ok=True)
ROOT_DATA.mkdir(parents=True, exist_ok=True)

DIGEST_NAME = "_digest.md"

=======
ROOT = Path(__file__).parent
DB_PATH = ROOT / "brain.db"
NOTES = ROOT / "notes"
NOTES.mkdir(exist_ok=True)

DIGEST_NAME = "_digest.md"

# ---------------------------------------------------------------- raw log

>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe

def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
<<<<<<< HEAD
            mode    TEXT NOT NULL DEFAULT 'coach',
=======
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
            role    TEXT NOT NULL,
            content TEXT NOT NULL,
            ts      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


<<<<<<< HEAD
def log_turn(role: str, content: str, mode: str = "coach") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO turns (mode, role, content) VALUES (?, ?, ?)",
            (mode, role, content),
        )


def load_recent(n: int = 16) -> list[dict]:
=======
def log_turn(role: str, content: str) -> None:
    """Append one message to the permanent log."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO turns (role, content) VALUES (?, ?)", (role, content)
        )


def load_recent(n: int = 12) -> list[dict]:
    """Last n turns, as OpenAI-style messages. This is the short-term window."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM turns "
            "WHERE role IN ('user', 'assistant') ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


# ---------------------------------------------------------------- notes

<<<<<<< HEAD
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

=======
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe

def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48] or "note").strip("-")


<<<<<<< HEAD
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
=======
_STOP = set(
    "the a an is are was were user i my me we our you your it its of to in on at "
    "for and or that this these those be been has have had do does did as with".split()
)


def _key(text: str) -> set[str]:
    """Words that carry meaning, so 'I am learning Python' and
    'The user is learning Python' look the same."""
    return _words(text) - _STOP


def keywords(text: str) -> set[str]:
    """Public alias: used by librarian.py to reject invented facts."""
    return _key(text)


def find_note(text: str) -> Path | None:
    """Return an existing note that says (roughly) the same thing."""
    target = _key(text)
    if not target:
        return None

    for path in NOTES.glob("*.md"):
        if path.name == DIGEST_NAME:
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        other = _key(body.split("---", 2)[-1])
        if not other or len(target & other) < 3:
            continue
        # Jaccard similarity: 1.0 = identical wording
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        if len(target & other) / len(target | other) >= 0.6:
            return path
    return None


def remember(text: str, tags: list[str] | None = None) -> Path:
<<<<<<< HEAD
=======
    """Write one fact to its own Markdown file. Returns the path.

    Never silently overwrites: a new file is created each time, so nothing
    you saved is ever lost. Deduping happens later, in consolidate.py.
    """
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    text = text.strip()
    if not text:
        raise ValueError("refusing to save an empty note")

    existing = find_note(text)
    if existing:
        return existing

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = NOTES / f"{stamp}-{_slug(text)}.md"
    tag_line = ", ".join(t.strip() for t in (tags or []) if t.strip())
<<<<<<< HEAD
=======

>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    path.write_text(
        f"---\ncreated: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"tags: {tag_line}\n---\n\n{text}\n",
        encoding="utf-8",
    )
    log_turn("memory", f"saved {path.name}")
    return path


<<<<<<< HEAD
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
    hits = _semantic_hits(query) or _keyword_hits(query)
    if not hits:
        hits = [(0.0, p) for p in _recent(3)]

    chunks, used = [], 0
    for _, path in hits[:k]:
        body = _body(path)
=======
_WORD = re.compile(r"[a-z0-9]{3,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def recall(query: str, k: int = 5, budget: int = 3000) -> str:
    """Keyword search over the note vault. Cheap, transparent, good enough.

    This is v3 of the ladder. When it stops being good enough, replace the
    scoring with embeddings -- everything else (the interface) stays identical.
    """
    wanted = _words(query)
    if not wanted:
        return ""

    scored: list[tuple[float, Path, str]] = []
    for path in NOTES.glob("*.md"):
        if path.name.startswith("_"):
            continue  # generated files are not facts
        body = path.read_text(encoding="utf-8", errors="ignore")
        found = wanted & _words(body)
        if not found:
            continue
        # score = share of the question's words that appear in the note
        score = len(found) / (len(wanted) ** 0.5)
        scored.append((score, path, body))

    scored.sort(key=lambda row: (-row[0], -row[1].stat().st_mtime))

    if not scored:
        # Nothing matched. With a small vault, show the newest notes so that
        # "what do you know about me?" still gets a real answer. This is a
        # deliberately crude fallback; delete it once you have >50 notes.
        recent = sorted(NOTES.glob("*.md"), key=lambda p: -p.stat().st_mtime)
        scored = [
            (0.0, p, p.read_text(encoding="utf-8", errors="ignore"))
            for p in recent
            if not p.name.startswith("_")
        ][:3]

    chunks, used = [], 0
    for _, path, body in scored[:k]:
        body = body.split("---", 2)[-1].strip()  # drop frontmatter
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
        if used + len(body) > budget:
            body = body[: max(0, budget - used)] + "…"
        chunks.append(f"[{path.stem}]\n{body}")
        used += len(body)
        if used >= budget:
            break
<<<<<<< HEAD
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
=======

    return "\n\n".join(chunks)


def digest(max_chars: int = 1200) -> str:
    """The consolidated summary, if consolidate.py has produced one."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    path = NOTES / DIGEST_NAME
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]


<<<<<<< HEAD
=======
def note_paths() -> list[Path]:
    """Real notes only. Files starting with '_' are generated (digest,
    reflection) and must never be treated as things you wrote."""
    return sorted(p for p in NOTES.glob("*.md") if not p.name.startswith("_"))


# ---------------------------------------------------------------- cli

>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
if __name__ == "__main__":
    import sys

    if "--stats" in sys.argv:
        with _conn() as conn:
            turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
<<<<<<< HEAD
        print(f"turns : {turns}")
        print(f"notes : {len(note_paths())}")
        print(f"db    : {DB_PATH}")
        print(f"vault : {NOTES}")
=======
        print(f"turns in log : {turns}")
        print(f"notes        : {len(note_paths())}")
        print(f"db           : {DB_PATH}")
        print(f"vault        : {NOTES}")
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    elif len(sys.argv) > 1:
        print(recall(" ".join(sys.argv[1:])) or "(no matches)")
    else:
        print("usage: python memory.py --stats | python memory.py <query>")
