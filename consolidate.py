"""The 'sleep' job: consolidation.

Run this after a session (or nightly). It reads every note, asks the model to
compress them into one summary, and writes notes/_digest.md -- which is the
first thing every new conversation sees.

This is the closest thing to "training" you get for free: the brain gets
denser without touching any weights.

    uv run python consolidate.py
    uv run python consolidate.py --dry-run   # show the summary, save nothing
"""

from __future__ import annotations

import datetime as dt
import sys

import memory
from llm import chat

PROMPT = """You are compacting a personal knowledge vault.

I will give you the current summary and a list of notes. Rewrite them into a
single dense summary.

Rules:
- Keep every durable fact: preferences, decisions, names, ongoing projects.
- Merge duplicates. Drop small talk and one-off questions.
- Prefer concrete over vague. Keep dates when they matter.
- Maximum 40 bullet points. Use "##" headings to group by topic.
- Never invent anything that is not in the input.
- Output Markdown only, no preamble.

CURRENT SUMMARY
--------------
{current}

NEW NOTES ({count})
--------------
{notes}
"""


def collapse(notes_text: str, budget: int = 20_000) -> str:
    """Keep the newest notes in full; older ones get truncated."""
    if len(notes_text) <= budget:
        return notes_text
    return notes_text[-budget:]


def main() -> None:
    dry = "--dry-run" in sys.argv

    bodies = []
    for path in memory.note_paths():
        if path.name == memory.DIGEST_NAME:
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        bodies.append(f"### {path.name}\n{body.split('---', 2)[-1].strip()}")

    if len(bodies) < 3:
        print(f"Only {len(bodies)} note(s). Nothing to consolidate yet.")
        return

    prompt = PROMPT.format(
        current=memory.digest(max_chars=4000) or "(none)",
        count=len(bodies),
        notes=collapse("\n\n".join(bodies)),
    )
    print(f"consolidating {len(bodies)} notes…")
    summary = chat([{"role": "user", "content": prompt}]).content or ""

    if dry:
        print("\n" + summary)
        return

    out = memory.NOTES / memory.DIGEST_NAME
    out.write_text(
        f"<!-- regenerated {dt.datetime.now().isoformat(timespec='seconds')} "
        f"from {len(bodies)} notes -->\n\n{summary}\n",
        encoding="utf-8",
    )
    print(f"wrote {out}  ({len(summary)} chars)")


if __name__ == "__main__":
    main()
