"""CLI for Atlas tools. Uses exactly the same code as the chat tools.

    atlas tools                         list tools and their status
    atlas tools configure --workspace ~/dev/my-project
    atlas net search "query" [--limit 5]
    atlas net fetch https://example.com
    atlas fs list [path]
    atlas fs read  path
    atlas fs write path --text "..."   (or pipe text on stdin)
"""

from __future__ import annotations

import argparse
import json
import sys

import fstools
import netguard
import webtools

WEB_TOOLS = [
    {"name": "web_search", "status": "available", "note": "DuckDuckGo HTML (no key) or Brave if ATLAS_BRAVE_KEY is set"},
    {"name": "web_fetch", "status": "available", "note": "public http(s), SSRF-checked"},
]


def main() -> int:
    parser = argparse.ArgumentParser(prog="atlas tools")
    sub = parser.add_subparsers(dest="group", required=True)

    tools = sub.add_parser("tools", help="list and configure tools")
    tools_sub = tools.add_subparsers(dest="action")
    tools_sub.add_parser("list")
    tools_sub.add_parser("status")
    configure = tools_sub.add_parser("configure")
    configure.add_argument("--workspace", help="directory the filesystem tool may access")

    net = sub.add_parser("net", help="web search and fetch")
    net_sub = net.add_subparsers(dest="action", required=True)
    search = net_sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    fetch = net_sub.add_parser("fetch")
    fetch.add_argument("url")

    fs = sub.add_parser("fs", help="workspace-confined filesystem")
    fs_sub = fs.add_subparsers(dest="action", required=True)
    read = fs_sub.add_parser("read")
    read.add_argument("path")
    listing = fs_sub.add_parser("list")
    listing.add_argument("path", nargs="?", default=".")
    write = fs_sub.add_parser("write")
    write.add_argument("path")
    write.add_argument("--text", help="content; omit to read stdin")

    args = parser.parse_args()

    try:
        if args.group == "tools":
            if args.action == "configure":
                if not args.workspace:
                    parser.error("--workspace is required")
                print("workspace:", fstools.configure_workspace(args.workspace))
                return 0
            rows = [
                {"name": "web_search", "status": "available", "note": "public web, no key required"},
                {"name": "web_fetch", "status": "available", "note": "SSRF-checked http(s)"},
                {"name": "filesystem", "status": "available" if fstools.status()["available"] else "not configured",
                 "note": fstools.status().get("workspace") or "run: atlas tools configure --workspace PATH"},
            ]
            for row in rows:
                if args.action == "status":
                    print(json.dumps(row))
                else:
                    print(f"{row['name']:14} {row['status']:14} {row.get('note') or row.get('workspace') or ''}")
            return 0

        if args.group == "net":
            if args.action == "search":
                print(webtools.format_search(args.query, args.limit))
            else:
                print(webtools.fetch_page(args.url))
            return 0

        if args.action == "read":
            print(fstools.read(args.path))
        elif args.action == "list":
            print(fstools.list_dir(args.path))
        else:
            content = args.text if args.text is not None else sys.stdin.read()
            print(fstools.write(args.path, content))
        return 0
    except (netguard.NetError, fstools.ToolError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
