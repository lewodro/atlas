"""CLI for profiles and structured memory. Same backend as the GUI.

    atlas user list|create NAME|switch ID
    atlas memory list|search QUERY|add CATEGORY TEXT|correct ID TEXT
    atlas memory forget ID|import [FILE]|export|clear [--yes]
"""

from __future__ import annotations

import argparse
import json
import sys

import profiles


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="group", required=True)

    user = sub.add_parser("user")
    user_sub = user.add_subparsers(dest="action", required=True)
    user_sub.add_parser("list")
    create = user_sub.add_parser("create")
    create.add_argument("name")
    switch = user_sub.add_parser("switch")
    switch.add_argument("id")

    memory = sub.add_parser("memory")
    mem_sub = memory.add_subparsers(dest="action", required=True)
    listing = mem_sub.add_parser("list")
    listing.add_argument("--category")
    search = mem_sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("-k", type=int, default=6)
    add = mem_sub.add_parser("add")
    add.add_argument("category", choices=sorted(profiles.CATEGORIES))
    add.add_argument("text")
    add.add_argument("--confidence", type=float, default=0.7)
    correct = mem_sub.add_parser("correct")
    correct.add_argument("id", type=int)
    correct.add_argument("text")
    forget = mem_sub.add_parser("forget")
    forget.add_argument("id", type=int)
    imp = mem_sub.add_parser("import")
    imp.add_argument("file", nargs="?",
                     help="JSON backup from `atlas memory export FILE`, or a seed-note folder")
    exp = mem_sub.add_parser("export")
    exp.add_argument("file", nargs="?", help="write the JSON backup here (default: stdout)")
    clear = mem_sub.add_parser("clear")
    clear.add_argument("--yes", action="store_true")

    args = parser.parse_args()
    user_id = profiles.active()

    if args.group == "user":
        if args.action == "list":
            for row in profiles.list_profiles():
                mark = "*" if row["active"] else " "
                print(f"{mark} {row['id']:12} {row['name']:28} {row['memories']} memories")
        elif args.action == "create":
            print(profiles.create(args.name))
        elif args.action == "switch":
            print(profiles.switch(args.id))
        return

    if args.action == "list":
        rows = profiles.list_all(user_id, args.category)
        for row in rows:
            print(f"{row['id']:4} [{row['category']:12}] ({row['confidence']:.2f}) "
                  f"{row['content'][:90]}")
        print(f"{len(rows)} memories · profile {user_id}")
    elif args.action == "search":
        for row in profiles.search(user_id, args.query, args.k):
            print(f"{row['id']:4} [{row['category']:12}] {row['content'][:120]}")
    elif args.action == "add":
        memory_id, status = profiles.add(user_id, args.category, args.text,
                                         confidence=args.confidence)
        print(f"{status} memory {memory_id}")
    elif args.action == "correct":
        profiles.update(args.id, user_id, args.text, source="correction")
        print(f"corrected memory {args.id}")
    elif args.action == "forget":
        print("forgot" if profiles.forget(args.id, user_id) else "no such memory")
    elif args.action == "export":
        from pathlib import Path

        data = profiles.export(user_id)
        if args.file:
            path = Path(args.file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"exported {len(data['memories'])} memories from profile "
                  f"{user_id} to {path}")
        else:
            print(json.dumps(data, indent=2, ensure_ascii=False))
    elif args.action == "import":
        from pathlib import Path

        path = Path(args.file).expanduser() if args.file else None
        if path and path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except OSError as exc:
                sys.exit(f"cannot read {path}: {exc}")
            except json.JSONDecodeError as exc:
                sys.exit(f"{path} is not valid JSON: {exc}")
            try:
                result = profiles.import_data(payload)
            except ValueError as exc:
                sys.exit(f"invalid memory file: {exc}")
            print(f"imported {result['imported']}, duplicates {result['duplicates']}, "
                  f"skipped {result['skipped']} · profile {result['profile']}")
        else:
            # Legacy Markdown seed notes; no arbitrary code is executed.
            from scripts import import_seed
            import_seed.main(folder=str(path) if path else None)
    elif args.action == "clear":
        if not args.yes:
            sys.exit("refusing to clear without --yes")
        print(f"deleted {profiles.clear(user_id)} memories")


if __name__ == "__main__":
    main()
