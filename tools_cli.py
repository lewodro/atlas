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

import artifacts
import fstools
import goals
import netguard
import orchestrator
import registry
import research
import skills
import webtools
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
    tools_sub.add_parser("custom-init")
    tools_sub.add_parser("custom-list")
    tools_sub.add_parser("custom-validate")

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

    policy = sub.add_parser("policy", help="learned tool success rates and past plans")
    policy.add_argument("text", nargs="*")
    policy.add_argument("--export", metavar="FILE", help="save learned data to a JSON file")
    policy.add_argument("--import", dest="import_file", metavar="FILE",
                        help="merge learned data from a JSON file")

    fleet = sub.add_parser("fleet", help="controller for multiple Atlas agent instances")
    fleet_sub = fleet.add_subparsers(dest="action", required=True)
    fleet_sub.add_parser("list")
    fleet_sub.add_parser("shared")
    create_fleet = fleet_sub.add_parser("create")
    create_fleet.add_argument("label")
    create_fleet.add_argument("workspace")
    create_fleet.add_argument("--provider", default="ollama")
    create_fleet.add_argument("--model", default="")
    for action in ("start", "stop", "remove"):
        item = fleet_sub.add_parser(action)
        item.add_argument("id")
    goal_cmd = fleet_sub.add_parser("goal")
    goal_cmd.add_argument("text", nargs="+")
    goal_cmd.add_argument("--ids", nargs="*", default=None)

    bridge = sub.add_parser("bridge", help="local model briefs a frontier model")
    bridge.add_argument("text", nargs="+")
    bridge.add_argument("--no-refine", action="store_true")

    sub.add_parser("workspace", help="show workspace and Git context")

    company = sub.add_parser("company", help="real, dated company research")
    company.add_argument("name", nargs="+")
    company.add_argument("--sources", type=int, default=None)
    company.add_argument("--json", action="store_true")

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
            if args.action == "custom-init":
                import customtools
                print("example custom tool written to", customtools.create_example())
                return 0
            if args.action == "custom-list":
                import customtools
                for spec in customtools.load():
                    error = customtools.validate(spec)
                    state = "valid" if not error else f"invalid: {error}"
                    print(f"{str(spec.get('name')):18} {str(spec.get('kind')):8} {state}")
                if not customtools.load():
                    print("no custom tools; run: atlas tools custom-init")
                print("file:", customtools.FILE)
                return 0
            if args.action == "custom-validate":
                import customtools
                errors = [customtools.validate(spec) for spec in customtools.load()]
                failed = [error for error in errors if error]
                print("all custom tools valid" if not failed else "\n".join(failed))
                return 0 if not failed else 1
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

        if args.group == "policy":
            import examples
            import toolpolicy
            if args.export:
                count = toolpolicy.export_json(args.export)
                print(f"exported {count} learned records to {args.export}")
                return 0
            if args.import_file:
                counts = toolpolicy.import_json(args.import_file)
                print("imported:", json.dumps(counts))
                return 0
            text = " ".join(args.text).strip()
            if not text:
                print("Overall learned tool success (Beta posterior mean):")
                for row in toolpolicy.top():
                    print(f"  {row['tool']:16} {row['success']}/{row['n']} "
                          f"score={row['mean']:.2f}")
                return 0
            sig = toolpolicy.signature(text)
            print("signature:", sig)
            print(toolpolicy.prompt_hint(sig) or "no history for this task type yet")
            for row in examples.similar(text):
                tools = ", ".join(str(step.get("tool")) for step in row["steps"])
                print(f"  similar ({row['similarity']}): {row['goal']} -> {tools}")
            return 0

        if args.group == "fleet":
            import fleet
            if args.action == "list":
                for row in fleet.list_instances():
                    print(f"{row['id']:12} {row['label'][:20]:20} {row['provider']:12} "
                          f"port {row['port']} {row['status']}")
                if not fleet.list_instances():
                    print("no instances — create one with: atlas fleet create NAME PATH")
                return 0
            if args.action == "shared":
                print(fleet.shared_drive())
                print(fleet.sharetools.run({"action": "list", "path": "."}))
                return 0
            if args.action == "create":
                row = fleet.create(args.label, args.workspace, args.provider, args.model)
                print(json.dumps(row, indent=2))
                return 0
            if args.action in ("start", "stop", "remove"):
                fn = getattr(fleet, args.action)
                result = fn(args.id)
                print(json.dumps(result, indent=2, default=str))
                return 0
            result = fleet.orchestrate(" ".join(args.text), args.ids)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        if args.group == "bridge":
            import bridge
            result = bridge.run(" ".join(args.text), refine=not args.no_refine)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result.get("ok") else 1

        if args.group == "company":
            result = research.company(" ".join(args.name), sources=args.sources)
            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(result["digest"])
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
