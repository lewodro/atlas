"""Import the user-approved Markdown memory seed into the active profile.

    uv run python scripts/import_seed.py [--user PROFILE_ID] [--folder notes]

Each note's YAML-style frontmatter provides category, confidence, source and
creation date. The note body becomes the structured memory content. Existing
facts are deduplicated or reconciled by profiles.add(), never blindly copied.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import profiles  # noqa: E402


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3:
        return {}
    head = parts[1]

    def field(name: str, default: str = "") -> str:
        match = re.search(rf"(?m)^{name}:\s*(.+)$", head)
        return match.group(1).strip() if match else default

    category = field("category")
    if category not in profiles.CATEGORIES:
        return {}
    raw_confidence = field("confidence", "0.7").lower()
    confidence = {"high": 0.85, "medium": 0.6, "low": 0.35}.get(
        raw_confidence, float(raw_confidence) if raw_confidence.replace(".", "", 1).isdigit() else 0.6
    )
    return {
        "category": category,
        "content": parts[2].strip(),
        "source": field("source", "markdown seed"),
        "confidence": confidence,
        "created": field("created") or None,
    }


def main(folder: str | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=profiles.active())
    parser.add_argument("--folder", default=str(ROOT / "notes"))
    args = parser.parse_args()
    target = folder or args.folder

    source = Path(target)
    notes = (
        sorted(source.glob("*-seed-*.md")) if source.is_dir()
        else [source] if source.is_file() else []
    )
    counts = {"saved": 0, "known": 0, "updated": 0}
    for path in notes:
        item = parse(path)
        if not item:
            print(f"skip {path.name}: not a recognised seed note")
            continue
        _, status = profiles.add(
            args.user,
            item["category"],
            item["content"],
            source=item["source"],
            confidence=item["confidence"],
            created=item["created"],
        )
        counts[status] += 1
        print(f"{status:7} {item['category']:14} {path.name}")

    print(f"\n{counts['saved']} saved, {counts['updated']} updated, "
          f"{counts['known']} already known · profile {args.user}")


if __name__ == "__main__":
    main()
