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
from pathlib import Path

import artifacts
import fstools
import goals
import netguard
import codetools
import githubtools
import imagetools
import orchestrator
import providers
import registry
import research
import skills
import webtools
import workers
import dispatch
import workspace

WEB_TOOLS = [
    {"name": "web_search", "status": "available", "note": "DuckDuckGo HTML (no key) or Brave if ATLAS_BRAVE_KEY is set"},
    {"name": "web_fetch", "status": "available", "note": "public http(s), SSRF-checked"},
]


class patch_sys_argv:
    def __init__(self, values):
        self.values = values
        self.saved = None

    def __enter__(self):
        self.saved = sys.argv
        sys.argv = self.values
        return self

    def __exit__(self, *args):
        sys.argv = self.saved


def main() -> int:
    parser = argparse.ArgumentParser(prog="atlas tools")
    sub = parser.add_subparsers(dest="group", required=True)

    tools = sub.add_parser("tools", help="list and configure tools")
    tools_sub = tools.add_subparsers(dest="action")
    tools_sub.add_parser("list")
    tools_sub.add_parser("status")
    configure = tools_sub.add_parser("configure")
    configure.add_argument("--workspace", help="directory the filesystem tool may access")
    run = tools_sub.add_parser("run")
    run.add_argument("id")
    run.add_argument("--args", default="{}", help="JSON object of tool arguments")
    tools_sub.add_parser("permissions")

    skill = sub.add_parser("skills", help="installed instruction skills")
    skill_sub = skill.add_subparsers(dest="action", required=True)
    skill_sub.add_parser("list")
    show = skill_sub.add_parser("show")
    show.add_argument("id")
    enable = skill_sub.add_parser("enable")
    enable.add_argument("id")
    disable = skill_sub.add_parser("disable")
    disable.add_argument("id")

    art = sub.add_parser("artifacts", help="files Atlas created or used")
    art_sub = art.add_subparsers(dest="action", required=True)
    art_sub.add_parser("list")
    art_show = art_sub.add_parser("show")
    art_show.add_argument("id")

    fm = sub.add_parser("fm", help="workspace file manager")
    fm_sub = fm.add_subparsers(dest="action", required=True)
    for action in ("list", "read", "mkdir", "delete"):
        item = fm_sub.add_parser(action)
        item.add_argument("path", nargs="?", default=".")
    write = fm_sub.add_parser("write")
    write.add_argument("path")
    write.add_argument("--text", help="content; omit to read stdin")
    move = fm_sub.add_parser("move")
    move.add_argument("source")
    move.add_argument("destination")

    term = sub.add_parser("term", help="allowlisted read-only terminal command")
    term.add_argument("command", nargs=argparse.REMAINDER)

    agents = sub.add_parser("agents", help="roles and instances")
    agents_sub = agents.add_subparsers(dest="action", required=True)
    agents_sub.add_parser("roles")
    agents_sub.add_parser("list")
    agent_plan = agents_sub.add_parser("plan")
    agent_plan.add_argument("text", nargs="+")
    agent_create = agents_sub.add_parser("create")
    agent_create.add_argument("label")
    agent_create.add_argument("workspace")
    agent_remove = agents_sub.add_parser("remove")
    agent_remove.add_argument("id")
    agent_run = agents_sub.add_parser("run")
    agent_run.add_argument("id")
    agent_run.add_argument("--port", type=int, default=7777)

    goal = sub.add_parser("goal", help="set or view the agent goal")
    goal_sub = goal.add_subparsers(dest="action", required=True)
    set_goal = goal_sub.add_parser("set")
    set_goal.add_argument("text", nargs="+")
    goal_sub.add_parser("status")
    goal_sub.add_parser("clear")

    research_cmd = sub.add_parser("research", help="dated web research with sources")
    research_cmd.add_argument("topic", nargs="+")
    research_cmd.add_argument("--days", type=int, default=60)
    research_cmd.add_argument("--category", default="general",
                              choices=["finance", "news", "gaming", "ai", "general"])

    wrk = sub.add_parser("workers", help="manage isolated local Atlas workers")
    wrk_sub = wrk.add_subparsers(dest="action", required=True)
    wrk_sub.add_parser("list")
    wrk_create = wrk_sub.add_parser("create")
    wrk_create.add_argument("label")
    wrk_create.add_argument("--workspace", required=True)
    wrk_create.add_argument("--model", default="")
    wrk_create.add_argument("--role", default="general",
                            choices=sorted(orchestrator.ROLES))
    wrk_create.add_argument("--base-url", default="")
    wrk_create.add_argument("--port", type=int, default=0)
    wrk_start = wrk_sub.add_parser("start")
    wrk_start.add_argument("id")
    wrk_stop = wrk_sub.add_parser("stop")
    wrk_stop.add_argument("id")
    wrk_remove = wrk_sub.add_parser("remove")
    wrk_remove.add_argument("id")
    wrk_ask = wrk_sub.add_parser("ask")
    wrk_ask.add_argument("id")
    wrk_ask.add_argument("message", nargs="+")

    orch = sub.add_parser("orchestrate", help="run a goal across local workers")
    orch.add_argument("goal", nargs="+")
    orch.add_argument("--workers", nargs="*", default=None)
    orch.add_argument("--workspace", default="", help="target project folder")
    orch.add_argument("--no-synthesis", action="store_true")
    orch.add_argument("--sequential", action="store_true",
                      help="run workers in order so they can exchange files")
    orch.add_argument("--timeout", type=int, default=240)

    gh = sub.add_parser("github", help="read-only GitHub queries")
    gh_sub = gh.add_subparsers(dest="action", required=True)
    for action in ("issues", "prs", "repo"):
        item = gh_sub.add_parser(action)
        item.add_argument("repo", nargs="?", default="")
        if action != "repo":
            item.add_argument("--state", default="open")
            item.add_argument("--limit", type=int, default=5)

    img = sub.add_parser("image", help="local SVG image tools")
    img_sub = img.add_subparsers(dest="action", required=True)
    gen = img_sub.add_parser("generate")
    gen.add_argument("prompt", nargs="+")
    gen.add_argument("--path", default="images/atlas-image.svg")
    gen.add_argument("--title", default="")
    edit = img_sub.add_parser("edit")
    edit.add_argument("path")
    edit.add_argument("--background", default="")
    edit.add_argument("--caption", default="")
    edit.add_argument("--scale", type=float, default=0)

    code = sub.add_parser("code", help="restricted Python execution")
    code.add_argument("source", nargs="?", help="Python code; omit to read stdin")

    prov = sub.add_parser("providers", help="external tool providers")
    prov_sub = prov.add_subparsers(dest="action", required=True)
    prov_sub.add_parser("list")
    preg = prov_sub.add_parser("register")
    preg.add_argument("id")
    preg.add_argument("manifest")
    prem = prov_sub.add_parser("remove")
    prem.add_argument("id")

    sub.add_parser("workspace", help="show workspace and Git context")

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
        if args.group == "agents":
            argv = ["atlas agents", args.action]
            if args.action == "plan":
                argv += args.text
            elif args.action == "create":
                argv += [args.label, args.workspace]
            elif args.action == "remove":
                argv += [args.id]
            elif args.action == "run":
                argv += [args.id, "--port", str(args.port)]
            with patch_sys_argv(argv):
                orchestrator.main()
            return 0

        if args.group == "github":
            payload = {"repo": args.repo}
            if args.action != "repo":
                payload.update({"state": args.state, "limit": args.limit})
            result = registry.run(
                {"issues": "github_issues", "prs": "github_prs", "repo": "github_repo"}[args.action],
                payload, approved=True,
            )
            print(registry.content(result))
            return 0 if result["ok"] else 1

        if args.group == "image":
            if args.action == "generate":
                result = registry.run("image_generate", {
                    "prompt": " ".join(args.prompt), "path": args.path,
                    "title": args.title,
                }, approved=True)
            else:
                payload = {"path": args.path}
                for key in ("background", "caption", "scale"):
                    value = getattr(args, key)
                    if value:
                        payload[key] = value
                result = registry.run("image_edit", payload, approved=True)
            print(registry.content(result))
            return 0 if result["ok"] else 1

        if args.group == "code":
            source = args.source if args.source is not None else sys.stdin.read()
            result = registry.run("code_execute", {"code": source}, approved=True)
            print(registry.content(result))
            return 0 if result["ok"] else 1

        if args.group == "providers":
            if args.action == "register":
                data = json.loads(Path(args.manifest).read_text())
                row = providers.register(args.id, data.get("name", ""),
                                         data.get("base_url", ""), data.get("tools", []))
                print(f"registered {row['id']} ({len(row['tools'])} tools)")
            elif args.action == "remove":
                print("removed" if providers.remove(args.id) else "no such provider")
            else:
                for row in providers.list_providers():
                    print(f"{row['id']:18} {row['base_url']:32} {len(row['tools'])} tools")
                if not providers.list_providers():
                    print("no providers registered")
            return 0

        if args.group == "workers":
            argv = ["atlas workers", args.action]
            if args.action == "create":
                argv += [args.label, "--workspace", args.workspace]
                for flag, value in (("--model", args.model), ("--role", args.role),
                                    ("--base-url", args.base_url)):
                    if value:
                        argv += [flag, value]
                if args.port:
                    argv += ["--port", str(args.port)]
            elif args.action in ("start", "stop", "remove"):
                argv += [args.id]
            elif args.action == "ask":
                argv += [args.id] + args.message
            with patch_sys_argv(argv):
                workers.main()
            return 0

        if args.group == "orchestrate":
            result = dispatch.orchestrate(
                " ".join(args.goal), args.workers,
                workspace=args.workspace,
                sequential=args.sequential,
                timeout=args.timeout,
                synthesize=not args.no_synthesis,
            )
            print(result["answer"] or json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        if args.group == "research":
            print(research.research(" ".join(args.topic), args.days,
                                    args.category)["digest"])
            return 0

        if args.group == "goal":
            if args.action == "set":
                item = goals.create(" ".join(args.text))
                print(f"goal set: {item['id']} · {item['text']}")
            elif args.action == "clear":
                item = goals.current()
                if item:
                    goals.finish(item["id"])
                print("goal cleared")
            else:
                item = goals.current()
                print(json.dumps(item, indent=2) if item else "no active goal")
            return 0

        if args.group == "fm":
            payload = {"action": args.action, "path": getattr(args, "path", ".")}
            if args.action == "write":
                payload["content"] = args.text if args.text is not None else sys.stdin.read()
            if args.action == "move":
                payload = {"action": "move", "path": args.source,
                           "destination": args.destination}
            result = registry.run("files", payload, approved=True)
            print(registry.content(result))
            return 0 if result["ok"] else 1

        if args.group == "term":
            result = registry.run("terminal", {"command": " ".join(args.command)})
            print(registry.content(result))
            return 0 if result["ok"] else 1

        if args.group == "workspace":
            print(json.dumps(workspace.context(), indent=2))
            return 0

        if args.group == "skills":
            if args.action == "list":
                for item in skills.list_skills():
                    mark = "+" if item["enabled"] else "-"
                    print(f"{mark} {item['id']:18} {item['description']}")
            elif args.action == "show":
                item = skills.load_skill(args.id)
                if not item:
                    print("error: no such skill", file=sys.stderr)
                    return 1
                print(item["body"])
            else:
                skills.set_enabled(args.id, args.action == "enable")
                print(f"{args.id}: {'enabled' if args.action == 'enable' else 'disabled'}")
            return 0

        if args.group == "artifacts":
            if args.action == "list":
                for item in artifacts.list_all():
                    print(f"{item['id']} [{item['kind']:8}] {item['title']}")
            else:
                item = artifacts.get(args.id)
                print(json.dumps(item, indent=2) if item else "no such artifact")
            return 0

        if args.group == "tools":
            if args.action == "permissions":
                for row in registry.metadata():
                    print(f"{row['id']:16} {row['permission']:6} {row['category']}")
                return 0
            if args.action == "run":
                result = registry.run(args.id, json.loads(args.args))
                print(json.dumps(result, indent=2))
                return 0 if result["ok"] else 1
            if args.action == "configure":
                if not args.workspace:
                    parser.error("--workspace is required")
                print("workspace:", fstools.configure_workspace(args.workspace))
                return 0
            for row in registry.metadata():
                if args.action == "status":
                    print(json.dumps(row))
                else:
                    state = "available" if row["available"] else "not configured"
                    print(f"{row['id']:16} {state:14} {row['permission']:6} {row['provider']:8} {row['description'][:60]}")
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
