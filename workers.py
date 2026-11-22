"""Local Atlas workers.

A worker is an isolated Atlas server process with its own workspace, memory,
notes, model and port. Workers are real local processes — no cloud accounts,
no remote orchestration service. Every safety rule (SSRF guard, workspace
confinement, permissions) applies inside each worker because it runs the same
server code.

    atlas workers create "Research" --model qwen2.5:3b --role research \
        --workspace ~/devAI/AtlasWSPC
    atlas workers start <id>
    atlas workers ask <id> "summarize this repo"
    atlas workers stop <id>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import config
import orchestrator

FILE = config.ROOT_DATA / "workers.json"
PORTS = range(7801, 7831)
ROLES = tuple(orchestrator.ROLES)


def _load() -> dict:
    if FILE.exists():
        try:
            value = json.loads(FILE.read_text())
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(data, indent=2) + "\n")


def list_workers() -> list[dict]:
    rows = list(_load().values())
    for row in rows:
        row["running"] = alive(row)
    return sorted(rows, key=lambda r: r["created"])


def get(worker_id: str) -> dict | None:
    return _load().get(worker_id)


def create(label: str, workspace: str, model: str = "", role: str = "general",
           base_url: str = "", port: int = 0) -> dict:
    label = str(label or "").strip()
    workspace = str(workspace or "").strip()
    if not label or not workspace:
        raise ValueError("label and workspace are required")
    if role not in ROLES:
        raise ValueError(f"role must be one of {', '.join(ROLES)}")

    data = _load()
    used = {row.get("port") for row in data.values()}
    if not port:
        port = next((p for p in PORTS if p not in used), 0)
        if not port:
            raise ValueError("no free worker ports")
    if port in used:
        raise ValueError(f"port {port} is already used by a worker")

    worker = {
        "id": "w-" + uuid.uuid4().hex[:8],
        "label": label,
        "workspace": str(Path(workspace).expanduser().resolve()),
        "model": model.strip() or config.MODEL,
        "role": role,
        "base_url": base_url.strip() or config.BASE_URL,
        "port": int(port),
        "pid": None,
        "created": int(time.time()),
    }
    data[worker["id"]] = worker
    _save(data)
    return worker


def remove(worker_id: str) -> bool:
    data = _load()
    worker = data.get(worker_id)
    if not worker:
        return False
    if alive(worker):
        stop(worker_id)
    del data[worker_id]
    _save(data)
    root = data_dir(worker_id)
    return True


def data_dir(worker_id: str) -> Path:
    return config.ROOT_DATA / "workers" / worker_id


def env_for(worker: dict) -> dict:
    root = data_dir(worker["id"])
    return {
        **os.environ,
        "ATLAS_DATA_DIR": str(root),
        "ATLAS_WORKSPACE": worker["workspace"],
        "ATLAS_NOTES_DIR": str(root / "notes"),
        "ATLAS_BASE_URL": worker["base_url"],
        "ATLAS_MODEL": worker["model"],
        "PYTHONUNBUFFERED": "1",
    }


def alive(worker: dict) -> bool:
    pid = worker.get("pid")
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except OSError:
        return False
    return True


def start(worker_id: str, wait: float = 25.0) -> dict:
    data = _load()
    worker = data.get(worker_id)
    if not worker:
        raise ValueError(f"no such worker: {worker_id}")
    if alive(worker):
        return worker
    root = data_dir(worker_id)
    root.mkdir(parents=True, exist_ok=True)
    log = (root / "server.log").open("ab")
    process = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(worker["port"])],
        cwd=str(config.ROOT),
        env=env_for(worker),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    worker["pid"] = process.pid
    data[worker_id] = worker
    _save(data)

    deadline = time.time() + wait
    while time.time() < deadline:
        if healthy(worker):
            return worker
        if process.poll() is not None:
            raise RuntimeError(f"worker exited: {(root / 'server.log').read_text()[-300:]}")
        time.sleep(0.5)
    raise TimeoutError(f"worker {worker_id} did not start in {wait}s")


def stop(worker_id: str) -> bool:
    data = _load()
    worker = data.get(worker_id)
    if not worker:
        return False
    pid = worker.get("pid")
    if pid:
        try:
            os.killpg(os.getpgid(int(pid)), 15)
        except OSError:
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass
    worker["pid"] = None
    data[worker_id] = worker
    _save(data)
    return True


def healthy(worker: dict) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{worker['port']}/api/stats", timeout=2
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _post(port: int, path: str, payload: dict, timeout: int = 240):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(request, timeout=timeout)


def ask(worker_id: str, message: str, timeout: int = 240) -> dict:
    """Send one task to a worker. Returns its answer and real tool activity."""
    worker = get(worker_id)
    if not worker:
        raise ValueError(f"no such worker: {worker_id}")
    if not healthy(worker):
        raise RuntimeError(f"worker {worker_id} is not running")

    session = json.load(_post(worker["port"], "/api/sessions", {
        "mode": worker["role"], "model": worker["model"],
    }))
    response = _post(worker["port"], "/api/chat", {
        "session_id": session["id"], "message": message, "mode": worker["role"],
    }, timeout=timeout)

    answer, tools = "", []
    buffer = ""
    for raw in response:
        buffer += raw.decode("utf-8", "replace")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            name, data = "message", ""
            for line in block.splitlines():
                if line.startswith("event:"):
                    name = line[6:].strip()
                elif line.startswith("data:"):
                    data += line[5:].strip()
            if not data:
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if name == "permission":
                token = event.get("token")
                if token:
                    _post(worker["port"], "/api/tools/permission",
                          {"token": token, "allow": True}, timeout=10)
            elif name == "tool":
                tools.append({"name": event["name"], "ok": event.get("status") == "ok"})
            elif name == "done":
                answer = event.get("text", "")
            elif name == "error":
                answer = f"ERROR {event.get('message')}"

    return {
        "worker": worker["id"], "label": worker["label"],
        "role": worker["role"], "model": worker["model"],
        "answer": answer, "tools": tools,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="manage local Atlas workers")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list")
    create_cmd = sub.add_parser("create")
    create_cmd.add_argument("label")
    create_cmd.add_argument("--workspace", required=True)
    create_cmd.add_argument("--model", default="")
    create_cmd.add_argument("--role", default="general", choices=ROLES)
    create_cmd.add_argument("--base-url", default="")
    create_cmd.add_argument("--port", type=int, default=0)
    start_cmd = sub.add_parser("start")
    start_cmd.add_argument("id")
    stop_cmd = sub.add_parser("stop")
    stop_cmd.add_argument("id")
    remove_cmd = sub.add_parser("remove")
    remove_cmd.add_argument("id")
    ask_cmd = sub.add_parser("ask")
    ask_cmd.add_argument("id")
    ask_cmd.add_argument("message", nargs="+")
    args = parser.parse_args()

    if args.action == "list":
        for row in list_workers():
            state = "running" if row["running"] else "stopped"
            print(f"{row['id']}  {row['label']:18} {row['model']:24} "
                  f"{row['role']:10} :{row['port']}  {state}")
        if not list_workers():
            print("no workers — create one with: atlas workers create NAME --workspace PATH")
    elif args.action == "create":
        row = create(args.label, args.workspace, args.model, args.role,
                     args.base_url, args.port)
        print(f"{row['id']} {row['label']} -> {row['workspace']} on :{row['port']}")
    elif args.action == "start":
        row = start(args.id)
        print(f"started {row['id']} on http://127.0.0.1:{row['port']}")
    elif args.action == "stop":
        print("stopped" if stop(args.id) else "no such worker")
    elif args.action == "remove":
        print("removed" if remove(args.id) else "no such worker")
    elif args.action == "ask":
        result = ask(args.id, " ".join(args.message))
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
