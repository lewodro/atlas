"""Evaluation: does memory retrieve the right note?

Cheap (no model call), fast. Run it after every change to recall().

    uv run python seed.py
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
    return re.sub(r"[^a-z0-9]", "", text.lower())


def main() -> int:
    cases = json.loads((Path(__file__).parent / "questions.json").read_text())
    passed = 0

    for case in cases:
        hits = norm(memory.recall(case["query"]))
        hit = norm(case["expect"]) in hits
        passed += hit
        print(f"[{'pass' if hit else 'FAIL'}] {case['query']!r} -> {case['expect']!r}")

    print(f"\n{passed}/{len(cases)} passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
