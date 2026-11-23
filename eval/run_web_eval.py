"""Web-research evals: freshness enforcement and grounded answers.

    uv run python eval/run_web_eval.py          # fast, offline policy checks
    uv run python eval/run_web_eval.py --live   # real local model + real tools

No new facts are baked into the model or the prompt: these only check that
Atlas searches when it should, stays quiet when it should not, and is honest
when the web cannot be reached.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import freshness  # noqa: E402

# id -> (prompt, needs_web, search_fails)
CASES = {
    "A": (
        "What are the latest AI model releases in November 2026?", True, False
    ),
    "B": ("Who is the current CEO of OpenAI?", True, False),
    "C": ("What is Python list comprehension?", False, False),
    "D": ("Tell me about the Roman Empire.", False, False),
    "E": ("What are the latest security breaches this week?", True, True),
    "F": (
        "Research the latest AI tools and security breaches from November 2026.",
        True, False,
    ),
}


def offline() -> int:
    failed = 0
    for case_id, (prompt, needs_web, _) in CASES.items():
        detected = freshness.required(prompt)
        ok = detected == needs_web
        failed += not ok
        queries = freshness.suggest_queries(prompt) if detected else []
        print(f"[{'pass' if ok else 'FAIL'}] {case_id} freshness={detected} "
              f"queries={queries[:3]}")
    return 1 if failed else 0


def live() -> int:
    import main
    import registry

    original = registry.run
    failed = 0
    for case_id, (prompt, needs_web, search_fails) in CASES.items():
        calls: list[tuple[str, str]] = []

        def spy(tool, args=None, **kwargs):
            args = args or {}
            calls.append((tool, str(args.get("query") or args.get("url") or "")[:60]))
            if search_fails and tool == "web_search":
                return {"tool": tool, "ok": True,
                        "data": "No usable results for 'x'.", "error": None,
                        "duration_ms": 0}
            return original(tool, args, **kwargs)

        try:
            with patch.object(registry, "run", side_effect=spy), \
                 patch.object(main, "journal"):
                answer = main.turn(
                    [{"role": "system", "content": ""}],
                    prompt, "general", write_memory=False,
                )
        except Exception as exc:  # a live model can fail; report, don't crash
            print(f"[FAIL] {case_id} raised {type(exc).__name__}: {exc}")
            failed += 1
            continue

        web = [call for call in calls if call[0] in ("web_search", "web_fetch")]
        if search_fails:
            ok = "couldn't verify" in answer.lower()
        elif needs_web:
            ok = any(name == "web_search" for name, _ in web)
        else:
            ok = not web
        failed += not ok
        print(f"\n[{'pass' if ok else 'FAIL'}] {case_id}: {prompt}")
        print(f"  tools: {web or 'none'}")
        print(f"  answer: {' '.join(answer.split())[:320]}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true",
                        help="run the real configured local model and tools")
    parser.add_argument("--case", help="run only one case id (A-F) in live mode")
    args = parser.parse_args()
    if args.live and args.case:
        global CASES
        CASES = {args.case: CASES[args.case]}
    return live() if args.live else offline()


if __name__ == "__main__":
    raise SystemExit(main())
