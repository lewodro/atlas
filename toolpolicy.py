"""Local, continuously learned tool-selection policy.

Atlas records every tool outcome it observes and keeps a small Bayesian
success estimate per (task signature, tool). This is the machine-learning part
of tool use: there is no cloud model and no large training run, just a Beta
posterior that is updated online after every real tool call.

The policy does not replace the registry's permission rules — it only ranks
tools that are already legal for the current task.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time

import config
import profiles

DB = config.ROOT_DATA / "atlas.db"

_STOP = set(
    "a an the and or but if then than that this these those of in on at to for "
    "from with by about into through over under is are was were be been being "
    "do does did done have has had can could would should will shall may might "
    "must not no nor so as too very more most some any all each every what which "
    "who whom when where why how please tell me give show find make create write "
    "file files code script app program test tests new now today i you my your "
    "it its they them their me we us our".split()
)

_INTENTS = (
    ("code", r"\b(?:write|create|make|edit|fix|debug|implement|refactor|build|"
             r"generate|patch|add|delete|remove)\b.*\b(?:file|script|code|"
             r"function|class|module|app|test|\.py|\.js|\.md)\b|\b(?:fix|debug)\b"),
    ("web", r"\b(?:research|search|look up|find|latest|news|current|sources?|"
            r"citation|verify|web|site|url)\b"),
    ("company", r"\b(?:company|revenue|earnings|stock|filings|investor|"
                r"annual report|10-k|market cap)\b"),
    ("git", r"\b(?:git|commit|branch|diff|repository|repo|status)\b"),
    ("math", r"\b(?:plot|graph|chart|calculate|solve|math|function)\b"),
)


def intent(text: str) -> str:
    low = str(text or "").lower()
    for label, pattern in _INTENTS:
        if re.search(pattern, low, re.I | re.S):
            return label
    return "general"


def signature(text: str) -> str:
    """Stable, compact fingerprint of a task for the learned policy."""
    words = [w for w in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
             if w not in _STOP]
    unique = sorted(set(words))[:8]
    return intent(text) + "|" + " ".join(unique)


def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tool_policy (
               sig      TEXT NOT NULL,
               tool     TEXT NOT NULL,
               user_id  TEXT NOT NULL,
               n        INTEGER NOT NULL DEFAULT 0,
               success  INTEGER NOT NULL DEFAULT 0,
               total_ms INTEGER NOT NULL DEFAULT 0,
               reward   REAL NOT NULL DEFAULT 0,
               reward_n INTEGER NOT NULL DEFAULT 0,
               updated  INTEGER NOT NULL,
               PRIMARY KEY (sig, tool, user_id)
           )"""
    )
    # Older databases predate the reward columns.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tool_policy)")}
    if "reward" not in columns:
        conn.execute("ALTER TABLE tool_policy ADD COLUMN reward REAL NOT NULL DEFAULT 0")
    if "reward_n" not in columns:
        conn.execute("ALTER TABLE tool_policy ADD COLUMN reward_n INTEGER NOT NULL DEFAULT 0")
    return conn


def record(sig: str, tool: str, ok: bool, duration_ms: int = 0) -> None:
    """Online update after one real tool observation."""
    try:
        user = profiles.active()
        with _conn() as conn:
            row = conn.execute(
                "SELECT n, success, total_ms FROM tool_policy "
                "WHERE sig=? AND tool=? AND user_id=?",
                (sig, tool, user),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE tool_policy SET n=n+1, success=success+?, "
                    "total_ms=total_ms+?, updated=? "
                    "WHERE sig=? AND tool=? AND user_id=?",
                    (int(bool(ok)), int(duration_ms), int(time.time()), sig, tool, user),
                )
            else:
                conn.execute(
                    "INSERT INTO tool_policy "
                    "(sig, tool, user_id, n, success, total_ms, updated) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (sig, tool, user, 1, int(bool(ok)), int(duration_ms), int(time.time())),
                )
    except (sqlite3.Error, OSError):
        pass


def stats(sig: str, limit: int = 6) -> list[dict]:
    """Posterior success estimates for tools used on similar tasks."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT tool, n, success, total_ms, reward, reward_n FROM tool_policy "
                "WHERE sig=? AND user_id=? AND n>0 ORDER BY n DESC LIMIT ?",
                (sig, profiles.active(), limit),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    return [
        {
            "tool": row[0], "n": row[1], "success": row[2],
            "mean": (1 + row[2]) / (2 + row[1]),
            "avg_ms": row[3] / max(1, row[1]),
            "reward": row[4] / max(1, row[5]),
            "reward_n": row[5],
        }
        for row in rows
    ]


def rank(tools: list[str], sig: str, explore: float = 0.0) -> list[str]:
    """Rank candidate tools by learned success (Thompson sampling if exploring).

    With explore=0 the ranking is deterministic — useful for tests and for
    small models that should not see random plans. A small epsilon at runtime
    keeps the policy from getting stuck on an early lucky tool.
    """
    prior = {row["tool"]: row for row in stats(sig, 12)}
    scored = []
    for tool in tools:
        row = prior.get(tool)
        if not row:
            score = 0.6  # untried tools get a fair, slightly cautious prior
        elif explore > 0:
            import random
            alpha, beta = 1 + row["success"], 1 + row["n"] - row["success"]
            score = random.betavariate(alpha, beta)
        else:
            # 70% observed success, 30% graded user feedback when available.
            feedback = 0.5 + 0.5 * max(-1.0, min(1.0, row["reward"]))
            score = 0.7 * row["mean"] + 0.3 * feedback if row["reward_n"] else row["mean"]
        # Very slow tools are mildly penalised; never disqualified.
        if row and row["avg_ms"] > 3000:
            score *= 0.9
        scored.append((score, tool))
    scored.sort(key=lambda item: -item[0])
    return [tool for _, tool in scored]


def prompt_hint(sig: str) -> str:
    rows = stats(sig, 4)
    if not rows:
        return ""
    bits = [f"{row['tool']} {row['success']}/{row['n']}" for row in rows]
    return "Local success history for this kind of task: " + ", ".join(bits) + "."


def top(limit: int = 10) -> list[dict]:
    """Overall tool success rates, useful for CLI diagnostics."""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT tool, SUM(n) AS n, SUM(success) AS success "
                "FROM tool_policy WHERE user_id=? GROUP BY tool "
                "ORDER BY n DESC LIMIT ?",
                (profiles.active(), limit),
            ).fetchall()
    except (sqlite3.Error, OSError):
        return []
    return [
        {"tool": row[0], "n": row[1], "success": row[2],
         "mean": (1 + row[2]) / (2 + row[1])}
        for row in rows if row[1]
    ]


def reward(sig: str, tool: str, value: float) -> None:
    """Fold explicit or graded feedback into the tool's local score."""
    try:
        with _conn() as conn:
            conn.execute(
                "UPDATE tool_policy SET reward=reward+?, reward_n=reward_n+1 "
                "WHERE sig=? AND tool=? AND user_id=?",
                (float(max(-1.0, min(1.0, value))), sig, tool, profiles.active()),
            )
    except (sqlite3.Error, OSError):
        pass


_LEARN_TABLES = ("tool_policy", "tool_examples", "feedback_events", "feedback_last")


def export_all() -> dict:
    """Portable snapshot of everything Atlas has learned locally."""
    payload: dict = {"version": 1}
    with _conn() as conn:
        for table in _LEARN_TABLES:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                payload[table] = [dict(row) for row in rows]
            except sqlite3.Error:
                payload[table] = []
    return payload


def import_all(payload: dict) -> dict:
    """Merge a learning snapshot into this profile's local database."""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("unrecognised learning snapshot")
    counts = {}
    with _conn() as conn:
        for table in _LEARN_TABLES:
            rows = payload.get(table) or []
            if not rows:
                counts[table] = 0
                continue
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            usable = [column for column in columns if column in rows[0]]
            placeholders = ",".join("?" for _ in usable)
            names = ",".join(usable)
            for row in rows:
                conn.execute(
                    f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})",
                    [row.get(column) for column in usable],
                )
            counts[table] = len(rows)
    return counts


def export_json(path: str) -> int:
    data = export_all()
    target = __import__("pathlib").Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return sum(len(value) for value in data.values() if isinstance(value, list))


def import_json(path: str) -> dict:
    source = __import__("pathlib").Path(path).expanduser()
    return import_all(json.loads(source.read_text()))
