"""The 'sleep' job: compress all notes into notes/_digest.md.

    uv run python consolidate.py [--dry-run]

This is the closest thing to training you get for free: the brain gets
denser without touching model weights.
"""

from __future__ import annotations

import datetime as dt
import sys

import memory
from llm import chat

PROMPT = """You are compacting a personal knowledge vault.

Rewrite the current summary plus the notes into one dense summary.

Rules:
- Keep durable facts: goals, skills, tools, hardware, constraints, decisions.
- Merge duplicates. Drop small talk and anything that was a one-off question.
- Group with "##" headings (e.g. Goals, Learning, Hardware, Constraints).
- Maximum 40 bullets. Concrete beats poetic. Keep dates when they matter.
- Never invent anything not present in the input.
- Output Markdown only, no preamble.

CURRENT SUMMARY
{current}

NOTES ({count})
{notes}
"""


def main() -> None:
    dry = "--dry-run" in sys.argv

    bodies = []
    for path in memory.note_paths():
        body = path.read_text(encoding="utf-8", errors="ignore")
        bodies.append(f"### {path.name}\n{body.split('---', 2)[-1].strip()}")

    if len(bodies) < 3:
        print(f"Only {len(bodies)} note(s). Write a few more first.")
        return

    text = "\n\n".join(bodies)[-20_000:]
    prompt = PROMPT.format(
        current=memory.digest(max_chars=4000) or "(none)",
        count=len(bodies),
        notes=text,
    )

    print(f"consolidating {len(bodies)} notes…")
    summary = chat([{"role": "user", "content": prompt}], temperature=0.2).content or ""

    if dry:
        print("\n" + summary)
        return

    out = memory.NOTES / memory.DIGEST_NAME
    out.write_text(
        f"<!-- regenerated {dt.datetime.now().isoformat(timespec='seconds')} "
        f"from {len(bodies)} notes -->\n\n{summary}\n",
        encoding="utf-8",
    )
    print(f"wrote {out} ({len(summary)} chars)")


if __name__ == "__main__":
    main()
