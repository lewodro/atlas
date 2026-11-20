"""Runtime context pack for small local models.

This file contains NO personal facts. Everything it returns is read at runtime
from local, gitignored state: the active profile's SQLite memories, the
configured workspace and the installed skills. The public repo ships only this
mechanism, never a user's data.
"""

from __future__ import annotations

import re

import fstools
import profiles
import skills
import workspace

PROJECT_WORDS = ("project", "repo", "repository", "workspace", "branch", "commit", "diff", "code")


def _facts(query: str, k: int = 4) -> list[str]:
    user = profiles.active()
    rows = profiles.search(user, query, k=k)
    low = query.lower()

    # Small models do not always form good FTS queries. Pull one canonical
    # fact per relevant category as well, without hardcoding any personal data.
    wanted = []
    if any(word in low for word in ("study", "studying", "student", "university", "course")):
        wanted.append("education")
    if any(word in low for word in ("project", "building", "working on", "repo")):
        wanted += ["projects", "last-seat"]
    if any(word in low for word in ("learn", "prefer", "explain")):
        wanted.append("learning")
    if "memory-rules" in low:
        wanted.append("memory-rules")
    for category in wanted:
        for row in profiles.list_all(user, category)[:1]:
            rows.insert(0, row)

    seen, facts = set(), []
    for row in rows:
        text = row["content"].strip()
        key = re.sub(r"\W+", "", text.lower())[:90]
        if not text or key in seen:
            continue
        seen.add(key)
        if row["category"] == "memory-rules":
            continue
        facts.append(f"- {text[:220]}")
        if len(facts) >= max(k, 3):
            break
    return facts


def _project_map() -> list[str]:
    parts = []
    try:
        inventory = fstools.list_dir(".").splitlines()[:14]
        parts.append("PROJECT FILES:\n" + "\n".join(inventory))
    except fstools.ToolError:
        pass
    try:
        readme = fstools.read("README.md", max_chars=600)
        body = readme.split(":\n", 1)[-1].strip()[:500]
        parts.append("README:\n" + body)
    except fstools.ToolError:
        pass
    return parts


def card(query: str, skill_id: str | None = None, limit: int = 1800) -> str:
    """Compact, bounded context assembled only from local runtime state."""
    parts: list[str] = []

    facts = _facts(query)
    if facts:
        parts.append("SAVED FACTS:\n" + "\n".join(facts))

    info = workspace.context()
    if info.get("configured"):
        if info.get("is_git"):
            state = "dirty" if info["dirty"] else "clean"
            parts.append(
                f"WORKSPACE: {info['root']} · repo {info['repo']} · "
                f"branch {info['branch'] or 'detached'} · {state} ({info['changed']} changed)"
            )
        else:
            parts.append(f"WORKSPACE: {info['root']} (no Git repository)")
        low = query.lower()
        if skill_id in ("project-explorer", "github-engineer") or any(
            word in low for word in PROJECT_WORDS
        ):
            parts.extend(_project_map())

    installed = [s["id"] for s in skills.list_skills() if s["enabled"]]
    if installed:
        parts.append("SKILLS INSTALLED: " + ", ".join(installed))

    return "\n\n".join(parts)[:limit]
