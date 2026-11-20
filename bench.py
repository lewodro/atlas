"""atlas bench — the numbers behind the README, measured, not guessed.

    uv run python bench.py                 # default: 2 runs per prompt
    uv run python bench.py --runs 3        # tighter estimate, ~2x the time
    uv run python bench.py --limit 4       # quick smoke test

Three measurements:

  1. tool calling   Does a small local model call the right tool with valid
                    arguments? Split by how it got there: a native tool_calls
                    field, or a <tool_call> block leaked into prose (which the
                    harness salvages). The gap between those two numbers is
                    the reason main.py has a salvage pass at all.

  2. retrieval      recall@5 over the questions in training/questions.json that
                    have a non-empty `expect`. A miss here is a memory bug you
                    can actually fix.

  3. latency        Median wall-clock seconds for a short, tool-free answer.

Writes docs/bench.json and prints a Markdown table. Nothing is written to
notes/ — the benchmark never executes a tool, it only inspects the call.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import llm
import memory
from config import MODEL, REMOTE, WHERE
from main import TOOLS, TOOL_TAG

ROOT = Path(__file__).parent
QUESTIONS = ROOT / "training" / "questions.json"
OUT = ROOT / "docs" / "bench.json"

# (prompt, expected tool, required argument keys)
TOOL_PROMPTS = [
    ("Remember that I use Neovim as my editor.", "remember", ["text"]),
    ("Save this: my algorithms exam is on Friday.", "remember", ["text"]),
    ("Note that I prefer terse answers with no filler.", "remember", ["text"]),
    ("Add a memory: I run five times a week.", "remember", ["text"]),
    ("What do you know about my editor?", "search_notes", ["query"]),
    ("Do you remember what I am studying?", "search_notes", ["query"]),
    ("What did I work on this week?", "recent_activity", []),
    ("Which projects did I touch yesterday?", "recent_activity", []),
]

LATENCY_PROMPTS = [
    "In one sentence, what is a stack?",
    "What is 17 * 3? Answer with the number only.",
    "Give me one reason to use a linked list.",
]

SYSTEM = "You are a terse assistant. Use the tools when the user asks you to remember something or asks about them."


def _valid(name: str, args, expected: str, required: list[str]) -> bool:
    if name != expected or not isinstance(args, dict):
        return False
    for key in required:
        value = args.get(key)
        if not isinstance(value, (str, int)) or not str(value).strip():
            return False
    return True


def _from_prose(text: str) -> tuple[str, dict] | None:
    """Pull a <tool_call>{...}</tool_call> block out of a model's prose."""
    if not text:
        return None
    match = TOOL_TAG.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    args = data.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    return data.get("name") or "", args


def bench_tools(runs: int, limit: int, model: str | None = None) -> dict:
    prompts = TOOL_PROMPTS[:limit] if limit else TOOL_PROMPTS
    counts = {"native": 0, "salvaged": 0, "prose": 0, "invalid": 0}
    runs_total = 0

    for prompt, expected, required in prompts:
        line = []
        for _ in range(runs):
            messages = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ]
            msg = llm.chat(messages, TOOLS, model=model)
            runs_total += 1

            native = None
            for call in msg.tool_calls or []:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if _valid(call.function.name, args, expected, required):
                    native = call.function.name
                    break

            if native:
                counts["native"] += 1
                line.append("native")
                continue

            prose = _from_prose(msg.content or "")
            if prose and _valid(prose[0], prose[1], expected, required):
                counts["salvaged"] += 1
                line.append("salvaged")
            elif msg.tool_calls or prose:
                counts["invalid"] += 1
                line.append("invalid")
            else:
                counts["prose"] += 1
                line.append("no call")

        print(f"  [{expected:14}] {prompt[:44]:46} {' '.join(line)}")

    def pct(n: int) -> float:
        return round(100 * n / runs_total, 1) if runs_total else 0.0

    return {
        "runs_per_prompt": runs,
        "prompts": len(prompts),
        "attempts": runs_total,
        "native": counts["native"],
        "salvaged": counts["salvaged"],
        "invalid": counts["invalid"],
        "no_call": counts["prose"],
        "native_pct": pct(counts["native"]),
        "usable_pct": pct(counts["native"] + counts["salvaged"]),
    }


def bench_recall() -> dict:
    questions = json.loads(QUESTIONS.read_text())
    scored = [q for q in questions if q.get("expect")]
    hits, misses = [], []

    for q in scored:
        context = memory.recall(q["query"], k=5)
        hit = q["expect"].lower() in context.lower()
        (hits if hit else misses).append(q["query"])
        print(f"  {'hit ' if hit else 'MISS'} {q['query'][:60]}")

    return {
        "questions": len(scored),
        "hits": len(hits),
        "recall_at_5": round(len(hits) / len(scored), 3) if scored else 0.0,
        "misses": misses,
    }


def bench_latency(model: str | None = None) -> dict:
    times = []
    for prompt in LATENCY_PROMPTS:
        started = time.perf_counter()
        llm.chat([
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ], model=model)
        elapsed = time.perf_counter() - started
        times.append(round(elapsed, 2))
        print(f"  {elapsed:5.2f}s  {prompt[:56]}")

    return {
        "prompts": len(times),
        "median_s": round(statistics.median(times), 2),
        "min_s": min(times),
        "max_s": max(times),
        "all_s": times,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="measure atlas on your hardware")
    parser.add_argument("--runs", type=int, default=2, help="attempts per tool prompt (default 2)")
    parser.add_argument("--limit", type=int, default=0, help="use only the first N tool prompts")
    parser.add_argument("--model", help="benchmark this model id instead of the configured default")
    parser.add_argument("--out", type=Path, default=OUT, help="where to write the JSON result")
    args = parser.parse_args()

    name = args.model or MODEL
    print(f"atlas bench · {name} · {'remote GPU' if REMOTE else 'this machine'} · {WHERE}")
    try:
        llm.chat([{"role": "user", "content": "ping"}], model=args.model)
    except Exception as exc:
        sys.exit(f"cannot reach the model: {type(exc).__name__}: {exc}")

    print("\ntool calling")
    tools = bench_tools(args.runs, args.limit, args.model)

    print("\nretrieval")
    recall = bench_recall()

    print("\nlatency")
    latency = bench_latency(args.model)

    result = {
        "model": name,
        "where": WHERE,
        "tools": tools,
        "retrieval": recall,
        "latency": latency,
        "measured_at": time.strftime("%Y-%m-%d"),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")

    print("\n| measurement | result |")
    print("|---|---|")
    print(f"| tool call, native JSON | {tools['native']}/{tools['attempts']} · {tools['native_pct']}% |")
    print(f"| tool call, usable after salvage | {tools['native'] + tools['salvaged']}/{tools['attempts']} · {tools['usable_pct']}% |")
    print(f"| retrieval recall@5 | {recall['hits']}/{recall['questions']} · {recall['recall_at_5']} |")
    print(f"| latency, median | {latency['median_s']}s |")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
