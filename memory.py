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
            ts      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def log_turn(role: str, content: str, mode: str = "coach") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO turns (mode, role, content) VALUES (?, ?, ?)",
            (mode, role, content),
        )


def load_recent(n: int = 16) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM turns "
            "WHERE role IN ('user', 'assistant') ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


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
    tag_line = ", ".join(t.strip() for t in (tags or []) if t.strip())
    path.write_text(
        f"---\ncreated: {dt.datetime.now().isoformat(timespec='seconds')}\n"
        f"tags: {tag_line}\n---\n\n{text}\n",
        encoding="utf-8",
    )
    log_turn("memory", f"saved {path.name}")
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
    hits = _semantic_hits(query) or _keyword_hits(query)
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


if __name__ == "__main__":
    import sys

    if "--stats" in sys.argv:
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
