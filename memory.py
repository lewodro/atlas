"""Memory: the part that makes the brain outlive the chat.

Two stores, deliberately boring:

  1. brain.db  - SQLite log of every turn. Raw history. Never edited.
  2. notes/    - one Markdown file per fact. Human-readable. You can edit it.

The rule of thumb this file follows:
    * files you can open with `cat` beat any database you can't.

Run `python memory.py --stats` at any time to see what's in there.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "brain.db"
NOTES = ROOT / "notes"
NOTES.mkdir(exist_ok=True)

DIGEST_NAME = "_digest.md"

# ---------------------------------------------------------------- raw log


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS turns (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            role    TEXT NOT NULL,
            content TEXT NOT NULL,
            ts      TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    return conn


def log_turn(role: str, content: str) -> None:
    """Append one message to the permanent log."""
    with _conn() as conn:
        conn.execute(
            "INSERT INTO turns (role, content) VALUES (?, ?)", (role, content)
        )


def load_recent(n: int = 12) -> list[dict]:
    """Last n turns, as OpenAI-style messages. This is the short-term window."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM turns "
            "WHERE role IN ('user', 'assistant') ORDER BY id DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in reversed(rows)]


# ---------------------------------------------------------------- notes


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:48] or "note").strip("-")


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
        if len(target & other) / len(target | other) >= 0.6:
            return path
    return None


def remember(text: str, tags: list[str] | None = None) -> Path:
    """Write one fact to its own Markdown file. Returns the path.

    Never silently overwrites: a new file is created each time, so nothing
    you saved is ever lost. Deduping happens later, in consolidate.py.
    """
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
        if used + len(body) > budget:
            body = body[: max(0, budget - used)] + "…"
        chunks.append(f"[{path.stem}]\n{body}")
        used += len(body)
        if used >= budget:
            break

    return "\n\n".join(chunks)


def digest(max_chars: int = 1200) -> str:
    """The consolidated summary, if consolidate.py has produced one."""
    path = NOTES / DIGEST_NAME
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]


def note_paths() -> list[Path]:
    """Real notes only. Files starting with '_' are generated (digest,
    reflection) and must never be treated as things you wrote."""
    return sorted(p for p in NOTES.glob("*.md") if not p.name.startswith("_"))


# ---------------------------------------------------------------- cli

if __name__ == "__main__":
    import sys

    if "--stats" in sys.argv:
        with _conn() as conn:
            turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
        print(f"turns in log : {turns}")
        print(f"notes        : {len(note_paths())}")
        print(f"db           : {DB_PATH}")
        print(f"vault        : {NOTES}")
    elif len(sys.argv) > 1:
        print(recall(" ".join(sys.argv[1:])) or "(no matches)")
    else:
        print("usage: python memory.py --stats | python memory.py <query>")
