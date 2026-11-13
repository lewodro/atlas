"""Scoreboard: does Atlas still know you?

Reads training/questions.json. Questions with an empty "expect" are pending —
fill them in as the notes exist. Retrieval only: no model call, runs in ~3s.

    uv run python eval/run_eval.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402

QUESTIONS = ROOT / "training" / "questions.json"


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def main() -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
