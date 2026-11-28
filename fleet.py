"""Controller for several Atlas agent instances.

An instance is a separate Atlas web server process with its own data folder,
workspace, model/provider and port. All instances share one drive (see
sharetools.py), so they can exchange files and HANDOFF.md messages.

The controller never sends anything itself except to localhost instances it
started. Frontier/hotbed egress stays explicit and visible in each instance's
own data/egress.jsonl.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
import orchestrator
import providers
import sharetools

FLEET = config.ROOT_DATA / "fleet.json"
BASE_PORT = 7800


def _load() -> dict:
    if FLEET.exists():
        try:
            value = json.loads(FLEET.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            return {}
    return {}


def _save(data: dict) -> None:
    FLEET.parent.mkdir(parents=True, exist_ok=True)
    FLEET.write_text(json.dumps(data, indent=2) + "\n")


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def _free_port() -> int:
    used = {int(row.get("port") or 0) for row in _load().values()}
    port = BASE_PORT
    while port in used or _port_open(port):
        port += 1
    return port


def shared_drive() -> Path:
    return sharetools.drive()


def create(label: str, workspace: str, provider: str = "ollama",
           model: str = "", role: str = "general") -> dict:
    label = str(label or "").strip()
    workspace = str(workspace or "").strip()
    if not label or not workspace:
        raise ValueError("label and workspace are required")
    if not providers.get(provider):
        raise ValueError(f"unknown provider {provider!r}")
    instance = orchestrator.create_instance(label, workspace)
    row = {
        "id": instance["id"], "label": label, "workspace": workspace,
        "provider": provider, "model": model, "role": role,
        "port": _free_port(), "pid": None, "status": "stopped",
        "shared": str(shared_drive()),
        "created": int(time.time()),
    }
    data = _load()
    data[row["id"]] = row
    _save(data)
    return row


def remove(instance_id: str) -> bool:
    stop(instance_id)
    data = _load()
    if instance_id not in data:
        return False
    del data[instance_id]
    _save(data)
    orchestrator.remove_instance(instance_id)
    return True


def list_instances() -> list[dict]:
    data = _load()
    dirty = False
    for row in data.values():
        status = "running" if _alive(row.get("pid")) else "stopped"
        if row.get("status") != status:
            row["status"] = status
            if status == "stopped":
                row["pid"] = None
            dirty = True
    if dirty:
        _save(data)
    return sorted(data.values(), key=lambda row: row["created"])


def start(instance_id: str) -> dict:
    data = _load()
    row = data.get(instance_id)
    if not row:
        raise ValueError(f"no such instance: {instance_id}")
    if _alive(row.get("pid")):
        return row
    preset = providers.get(row["provider"]) or {}
    if not preset["local"] and not providers.api_key(preset):
        raise RuntimeError(f"set {preset.get('key_env', 'API key')} in .env first")
    env = dict(os.environ)
    env.update(orchestrator.instance_env(instance_id))
    env["ATLAS_SHARED_DRIVE"] = row["shared"]
    env["ATLAS_BASE_URL"] = preset["base_url"]
    env["ATLAS_API_KEY"] = providers.api_key(preset)
    if row.get("model"):
        env["ATLAS_MODEL"] = row["model"]
    if not preset["local"]:
        # Each instance has its own settings.json; approve there too.
        settings = Path(env["ATLAS_DATA_DIR"]) / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        config_data = {}
        if settings.exists():
            try:
                config_data = json.loads(settings.read_text())
            except (OSError, json.JSONDecodeError, ValueError):
                config_data = {}
        config_data["remote_ok"] = True
        settings.write_text(json.dumps(config_data, indent=2) + "\n")

    log = Path(env["ATLAS_DATA_DIR"]) / "server.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    process = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(row["port"])],
        cwd=str(config.ROOT), env=env, stdout=handle, stderr=handle,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(40):
        if _port_open(row["port"]):
            break
        if process.poll() is not None:
            raise RuntimeError(f"instance exited: {log.read_text()[-400:]}")
        time.sleep(0.25)
    row.update({"pid": process.pid, "status": "running", "port": row["port"]})
    _save(data)
    return row


def stop(instance_id: str) -> bool:
    data = _load()
    row = data.get(instance_id)
    if not row:
        return False
    pid = row.get("pid")
    if _alive(pid):
        try:
            os.kill(int(pid), 15)
        except OSError:
            pass
        for _ in range(20):
            if not _alive(pid):
                break
            time.sleep(0.1)
    row.update({"pid": None, "status": "stopped"})
    _save(data)
    return True


def _request(url: str, payload: dict | None = None, timeout: int = 300) -> str:
    data = json.dumps(payload or {}).encode()
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def send_goal(instance_id: str, text: str, mode: str = "agent") -> dict:
    row = next((item for item in _load().values() if item["id"] == instance_id), None)
    if not row:
        return {"id": instance_id, "ok": False, "error": "no such instance"}
    if not _alive(row.get("pid")):
        return {"id": instance_id, "label": row["label"], "ok": False,
                "error": "instance is not running"}
    base = f"http://127.0.0.1:{row['port']}"
    try:
        session = json.loads(_request(base + "/api/sessions", {"mode": mode}, 15))["id"]
        stream = _request(base + "/api/chat", {
            "session_id": session, "message": text, "mode": mode,
        })
        answer = ""
        for line in stream.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if event.get("text"):
                answer = event["text"]
            if event.get("message"):
                answer = "ERROR: " + str(event["message"])
        sharetools.run({"action": "handoff", "note":
                        f"{row['label']} finished goal: {str(text)[:160]}"})
        return {"id": instance_id, "label": row["label"], "ok": True,
                "answer": answer, "session": session}
    except Exception as exc:
        return {"id": instance_id, "label": row["label"], "ok": False,
                "error": f"{type(exc).__name__}: {exc}"}


def orchestrate(goal: str, instance_ids: list[str] | None = None) -> dict:
    """Send one goal to several agents in parallel, then synthesize."""
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("goal is empty")
    sharetools.run({"action": "handoff", "note": f"ORCHESTRATOR GOAL: {goal[:600]}"})
    rows = list_instances()
    if instance_ids is not None:
        rows = [row for row in rows if row["id"] in instance_ids]
    active = [row for row in rows if row.get("status") == "running"]
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, len(active))) as pool:
        results = list(pool.map(lambda row: send_goal(row["id"], goal), active))
    synthesis = ""
    try:
        import bridge
        handoff = ""
        try:
            handoff = sharetools.run({"action": "read", "path": sharetools.HANDOFF})
        except Exception:
            pass
        digest = "\n\n".join(
            f"AGENT {item['label']}:\n{str(item.get('answer') or item.get('error'))[:1200]}"
            for item in results
        )
        bridged = bridge.run(
            f"Goal: {goal}\n\nAgent reports:\n{digest}\n\nShared handoff:\n{handoff[:1500]}"
        )
        if bridged.get("ok"):
            synthesis = bridged.get("answer", "")
        else:
            synthesis = (
                "Local synthesis (frontier tier not configured):\n"
                + "\n\n".join(
                    f"- {item['label']}: {str(item.get('answer') or item.get('error'))[:400]}"
                    for item in results
                )
            )
    except Exception as exc:
        synthesis = f"local synthesis unavailable: {exc}"
    return {"goal": goal, "agents": results, "synthesis": synthesis,
            "duration_s": round(time.time() - started, 1),
            "shared": str(shared_drive())}


def score_answer(goal: str, answer: str, ok: bool) -> tuple[int, list[str]]:
    """Deterministic, explainable grading of an agent's report."""
    text = str(answer or "")
    score, notes = 0, []
    if ok:
        score += 3
        notes.append("tool run succeeded")
    else:
        score -= 4
        notes.append("agent failed")
    if any(marker in text.lower() for marker in ("no answer", "could not establish",
                                                  "tool error", "(no answer)")):
        score -= 4
        notes.append("no grounded answer")
    for marker in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", str(goal or "")):
        if marker in text:
            score += 3
            notes.append(f"observed {marker}")
    if "http" in text:
        score += 2
        notes.append("cites a URL")
    if len(text) >= 80:
        score += 1
    if re.search(r"(?:^|\n)\s*[-*\d]+[.)]?\s", text):
        score += 1
        notes.append("structured report")
    return score, notes


def tournament(goal: str, instance_ids: list[str] | None = None) -> dict:
    """Run the same goal on several agents and pick a verified winner."""
    goal = str(goal or "").strip()
    if not goal:
        raise ValueError("goal is empty")
    rows = list_instances()
    if instance_ids is not None:
        rows = [row for row in rows if row["id"] in instance_ids]
    active = [row for row in rows if row.get("status") == "running"]
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, len(active))) as pool:
        results = list(pool.map(lambda row: send_goal(row["id"], goal), active))
    scored = []
    for item in results:
        value, notes = score_answer(goal, item.get("answer", ""), bool(item.get("ok")))
        scored.append({**item, "score": value, "notes": notes})
    scored.sort(key=lambda row: -row["score"])
    winner = scored[0] if scored else None
    receipt = (
        f"# Tournament winner\n\nGoal: {goal}\n\n"
        + (f"Agent: {winner['label']} (score {winner['score']})\n\n"
           f"{winner.get('answer', '')}\n" if winner else "No running agents.\n")
    )
    try:
        sharetools.run({"action": "write", "path": "WINNER.md", "content": receipt})
        sharetools.run({"action": "handoff",
                        "note": f"Tournament winner: {winner['label'] if winner else 'none'}"})
    except Exception:
        pass
    return {"goal": goal, "results": scored,
            "winner": winner["label"] if winner else None,
            "winner_id": winner["id"] if winner else None,
            "duration_s": round(time.time() - started, 1),
            "receipt": "WINNER.md"}
