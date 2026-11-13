<<<<<<< HEAD
"""Scoreboard: does Atlas still know you?

Reads training/questions.json. Questions with an empty "expect" are pending —
fill them in as the notes exist. Retrieval only: no model call, runs in ~3s.

=======
"""Evaluation: does memory actually retrieve the right note?

Cheap, fast, no model call -- it only tests recall(). Run it after every
change to memory.recall() or after a consolidation pass.

    uv run python seed.py          # once, to have something to retrieve
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    uv run python eval/run_eval.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

<<<<<<< HEAD
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402

QUESTIONS = ROOT / "training" / "questions.json"


def norm(text: str) -> str:
=======
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory  # noqa: E402


def norm(text: str) -> str:
    """Ignore spaces and punctuation: 'VS Code' == 'vscode'."""
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe
    return re.sub(r"[^a-z0-9]", "", text.lower())


def main() -> int:
<<<<<<< HEAD
    cases = json.loads(QUESTIONS.read_text())
    passed = failed = pending = 0

    for case in cases:
        expect = (case.get("expect") or "").strip()
        if not expect:
            pending += 1
            print(f"[todo] {case['query']!r}")
            continue
        hit = norm(expect) in norm(memory.recall(case["query"]))
        passed += hit
        failed += not hit
        print(f"[{'pass' if hit else 'FAIL'}] {case['query']!r} -> {expect!r}")

    total = passed + failed
    print(f"\n{passed}/{total} passed · {pending} pending (fill them in)")
    return 0 if failed == 0 else 1
=======
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
>>>>>>> d787cee333787e4d4ee9d4e9a4d633617d33a4fe


if __name__ == "__main__":
    raise SystemExit(main())
