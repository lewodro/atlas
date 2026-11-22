"""Coordinate several local Atlas workers toward one goal.

Workers run in parallel, each isolated and using its own local model. The main
model only synthesizes their reports — it does not pretend to do their work.
No cloud service, no account, no external coordinator.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import llm
import workers

ROLE_TASK = {
    "research": "Research this with real sources and cite URLs: {goal}",
    "engineer": "Inspect the workspace with tools and report concrete findings for: {goal}",
    "study": "Create concise study notes and one check question for: {goal}",
    "memory": "Recall stored personal context relevant to: {goal}. Do not guess.",
    "general": "{goal}",
}

SYSTEM = """You are the coordinator of several local Atlas workers.
Combine their reports into one clear answer in under 250 words.
- Keep only facts present in the reports. Never invent a source or number.
- If workers disagree, say so and give both claims.
- Name the source URLs that workers actually returned.
- Say what remains unknown."""


def orchestrate(goal: str, worker_ids: list[str] | None = None,
                synthesize: bool = True, timeout: int = 240) -> dict:
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("goal is empty")

    available = {row["id"]: row for row in workers.list_workers()}
    ids = worker_ids or list(available)
    if not ids:
        raise ValueError("no workers configured — create one with: atlas workers create NAME --workspace PATH")
    unknown = [wid for wid in ids if wid not in available]
    if unknown:
        raise ValueError(f"unknown workers: {', '.join(unknown)}")
    ids = ids[:6]  # bounded fan-out for consumer hardware

    started = int(time.time())
    for wid in ids:
        if not workers.healthy(available[wid]):
            workers.start(wid)

    tasks = {}
    for wid in ids:
        row = available[wid]
        template = ROLE_TASK.get(row["role"], ROLE_TASK["general"])
        tasks[wid] = template.format(goal=goal)

    reports: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(ids)) as pool:
        futures = {pool.submit(workers.ask, wid, text): wid
                   for wid, text in tasks.items()}
        for future in as_completed(futures, timeout=timeout):
            wid = futures[future]
            row = available[wid]
            try:
                report = future.result()
            except Exception as exc:
                report = {
                    "worker": wid, "label": row["label"], "role": row["role"],
                    "model": row["model"], "answer": f"FAILED: {type(exc).__name__}: {exc}",
                    "tools": [],
                }
            reports.append(report)

    answer = ""
    if synthesize and reports:
        text = "\n\n".join(
            f"WORKER {r['label']} ({r['role']}, {r['model']}):\n"
            f"{str(r['answer'])[:1800]}"
            for r in reports
        )[:9000]
        message = llm.chat(
            [{"role": "system", "content": SYSTEM},
             {"role": "user", "content": f"GOAL: {goal}\n\nREPORTS:\n{text}"}],
            None,
        )
        answer = message.content or ""

    return {
        "goal": goal,
        "workers": [r["worker"] for r in reports],
        "reports": reports,
        "answer": answer,
        "duration_s": round(time.time() - started, 1),
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="run a goal across local workers")
    parser.add_argument("goal", nargs="+")
    parser.add_argument("--workers", nargs="*", default=None)
    parser.add_argument("--no-synthesis", action="store_true")
    args = parser.parse_args()

    result = orchestrate(" ".join(args.goal), args.workers,
                         synthesize=not args.no_synthesis)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
