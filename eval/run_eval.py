"""Evaluation: does memory actually retrieve the right note?

Cheap, fast, no model call -- it only tests recall(). Run it after every
change to memory.recall() or after a consolidation pass.

    uv run python seed.py          # once, to have something to retrieve
    uv run python eval/run_eval.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory  # noqa: E402


def norm(text: str) -> str:
    """Ignore spaces and punctuation: 'VS Code' == 'vscode'."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def main() -> int:
    cases = json.loads((Path(__file__).parent / "questions.json").read_text())
    passed = 0

    for case in cases:
        hits = norm(memory.recall(case["query"]))
        hit = norm(case["expect"]) in hits
        passed += hit
        print(f"[{'pass' if hit else 'FAIL'}] {case['query']!r} -> {case['expect']!r}")

    total = len(cases)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
