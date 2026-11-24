"""Lightweight orchestrator for one Atlas agent with many roles.

There is one agent. Roles are just bundles of skills, never separate models or
prompt families. An instance is a named workspace + session pair so several
Atlas processes can run later without sharing state.

Nothing here calls a model or executes tools; it only selects which skills a
request should load and records instances locally.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import config
import freshness

INSTANCES_FILE = config.ROOT_DATA / "instances.json"


# A role names skills. It is not a mode and not a persona switch.
ROLES: dict[str, dict] = {
    "general": {
        "blurb": "one agent — asks, studies, builds, researches",
        "skills": [],
    },
    "study": {
        "blurb": "notes, summaries, maths and diagrams",
        "skills": ["study"],
    },
    "research": {
        "blurb": "search, fetch, cite",
        "skills": ["company-research", "web-research"],
    },
    "engineer": {
        "blurb": "inspect workspace, Git and code",
        "skills": ["project-explorer", "github-engineer"],
    },
    "memory": {
        "blurb": "recall and update personal context",
        "skills": ["personal-memory"],
    },
}

DEFAULT = "general"


def select_role(text: str) -> str:
    """Pick one role from the request. Cheap keyword pass, no model call."""
    low = str(text or "").lower()
    if freshness.required(text):
        return "research"
    if any(w in low for w in (
        "study", "notes", "summar", "explain", "graph", "function",
        "formula", "learn", "exam", "revision", "draw",
    )):
        return "study"
    if any(w in low for w in (
        "search", "research", "look up", "fetch", "current", "source", "cite",
        "company", "earnings", "revenue", "stock", "investor", "market cap",
    )):
        return "research"
    if any(w in low for w in (
        "repo", "git", "commit", "branch", "code", "project", "workspace",
        "file", "diff", "build", "terminal",
    )):
        return "engineer"
    if any(w in low for w in (
        "who am i", "what do you know", "remember", "forget", "my memory",
        "studying", "my name",
    )):
        return "memory"
    return DEFAULT


def plan(text: str) -> dict:
    """Return the role and the skills to load for this request."""
    role = select_role(text)
    return {"role": role, "skills": list(ROLES[role]["skills"]), "blurb": ROLES[role]["blurb"]}


def _instances() -> dict:
    if INSTANCES_FILE.exists():
        try:
            value = json.loads(INSTANCES_FILE.read_text())
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def list_instances() -> list[dict]:
    return sorted(_instances().values(), key=lambda row: row["created"])


def create_instance(label: str, workspace: str) -> dict:
    label = str(label or "").strip()
    workspace = str(workspace or "").strip()
    if not label or not workspace:
        raise ValueError("label and workspace are required")
    instance = {
        "id": "i-" + uuid.uuid4().hex[:8],
        "label": label,
        "workspace": workspace,
        "created": int(time.time()),
    }
    data = _instances()
    data[instance["id"]] = instance
    INSTANCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTANCES_FILE.write_text(json.dumps(data, indent=2) + "\n")
    return instance


def remove_instance(instance_id: str) -> bool:
    data = _instances()
    if instance_id not in data:
        return False
    del data[instance_id]
    INSTANCES_FILE.write_text(json.dumps(data, indent=2) + "\n")
    return True


def instance_env(instance_id: str) -> dict:
    """Environment for an isolated Atlas process. No shared memory or chats."""
    row = _instances().get(instance_id)
    if not row:
        raise ValueError(f"no such instance: {instance_id}")
    return {
        "ATLAS_DATA_DIR": str(config.ROOT_DATA / "instances" / instance_id),
        "ATLAS_WORKSPACE": row["workspace"],
        "ATLAS_PROFILE": instance_id,
        "ATLAS_NOTES_DIR": str(config.ROOT_DATA / "instances" / instance_id / "notes"),
    }


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Atlas agent roles and instances")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("roles")
    plan_cmd = sub.add_parser("plan")
    plan_cmd.add_argument("text", nargs="+")
    sub.add_parser("list")
    create = sub.add_parser("create")
    create.add_argument("label")
    create.add_argument("workspace")
    remove = sub.add_parser("remove")
    remove.add_argument("id")
    run = sub.add_parser("run")
    run.add_argument("id")
    run.add_argument("--port", type=int, default=7777)
    args = parser.parse_args()

    if args.action == "roles":
        for name, spec in ROLES.items():
            print(f"{name:10} {spec['blurb']:48} {', '.join(spec['skills']) or '-'}")
    elif args.action == "plan":
        print(json.dumps(plan(" ".join(args.text)), indent=2))
    elif args.action == "list":
        for row in list_instances():
            print(f"{row['id']}  {row['label']:24} {row['workspace']}")
        if not list_instances():
            print("no instances — create one with: atlas agents create NAME PATH")
    elif args.action == "create":
        row = create_instance(args.label, args.workspace)
        print(f"created {row['id']}: {row['label']} -> {row['workspace']}")
    elif args.action == "remove":
        print("removed" if remove_instance(args.id) else "no such instance")
    elif args.action == "run":
        import os
        import subprocess

        env = dict(os.environ)
        env.update(instance_env(args.id))
        raise SystemExit(subprocess.call(
            [sys.executable, "server.py", "--port", str(args.port)], env=env
        ))


if __name__ == "__main__":
    main()
