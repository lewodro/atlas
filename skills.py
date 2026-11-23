"""Skills are instructions, not capabilities.

Only name/description/tags are advertised at boot. The full SKILL.md body is
read only when a skill is selected or opened. No skill executes code.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import config
import freshness

SKILLS_DIR = config.ROOT / "skills"
CONFIG_FILE = config.ROOT_DATA / "skills.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,48}$")


def _disabled() -> set[str]:
    if CONFIG_FILE.exists():
        try:
            value = json.loads(CONFIG_FILE.read_text())
            return set(value.get("disabled", [])) if isinstance(value, dict) else set()
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def _set_disabled(values: set[str]) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps({"disabled": sorted(values)}, indent=2) + "\n")


def set_enabled(skill_id: str, enabled: bool) -> None:
    if not SAFE_ID.match(skill_id):
        raise ValueError("invalid skill id")
    disabled = _disabled()
    if enabled:
        disabled.discard(skill_id)
    else:
        disabled.add(skill_id)
    _set_disabled(disabled)


def _parse(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    if len(parts) != 3:
        return {}
    head, body = parts[1], parts[2].strip()

    def field(name: str, default: str = "") -> str:
        match = re.search(rf"(?m)^{name}:\s*(.+)$", head)
        return match.group(1).strip() if match else default

    def items(name: str) -> list[str]:
        value = field(name)
        return [x.strip() for x in value.strip("[]").split(",") if x.strip()]

    return {
        "id": path.parent.name,
        "name": field("name", path.parent.name),
        "description": field("description"),
        "tags": items("tags"),
        "tools": items("tools"),
        "body": body,
    }


def list_skills() -> list[dict]:
    disabled = _disabled()
    skills = []
    for folder in sorted(SKILLS_DIR.iterdir()) if SKILLS_DIR.exists() else []:
        if not folder.is_dir() or not SAFE_ID.match(folder.name):
            continue
        skill_file = folder / "SKILL.md"
        if not skill_file.exists():
            continue
        item = _parse(skill_file)
        if not item:
            continue
        item["enabled"] = folder.name not in disabled
        item.pop("body", None)  # lazy: metadata only
        skills.append(item)
    return skills


def load_skill(skill_id: str) -> dict | None:
    if not SAFE_ID.match(skill_id):
        return None
    path = SKILLS_DIR / skill_id / "SKILL.md"
    if not path.exists():
        return None
    item = _parse(path)
    if not item:
        return None
    item["enabled"] = skill_id not in _disabled()
    return item


def select_skill(text: str) -> str | None:
    """Keyword match against advertised metadata. No model call, no body read."""
    # Time-sensitive requests must load the research workflow, even when the
    # words happen to overlap another skill (e.g. "latest study results").
    if freshness.required(text) and any(
        s["id"] == "web-research" and s["enabled"] for s in list_skills()
    ):
        return "web-research"
    lowered = text.lower()
    if any(word in lowered for word in (
        "study", "notes", "note taking", "summarize", "summary", "explain",
        "graph", "function", "formula", "learn", "revision", "exam",
    )):
        skill = next((s for s in list_skills()
                      if s["id"] == "study" and s["enabled"]), None)
        if skill:
            return "study"
    if any(phrase in lowered for phrase in (
        "what do you know about me", "who am i", "what am i studying"
    )):
        return "personal-memory" if any(
            s["id"] == "personal-memory" and s["enabled"] for s in list_skills()
        ) else None
    words = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    if not words:
        return None
    best, score = None, 0
    for skill in list_skills():
        if not skill["enabled"]:
            continue
        haystack = set(re.findall(
            r"[a-z0-9]{3,}",
            (skill["name"] + " " + skill["description"] + " " + " ".join(skill["tags"])).lower(),
        ))
        hits = len(words & haystack)
        if hits > score:
            best, score = skill["id"], hits
    return best if score else None
