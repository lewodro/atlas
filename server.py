"""Atlas web UI — a localhost server, stdlib only.

    uv run python server.py            # http://localhost:7777
    uv run python server.py --port 8080

Why stdlib: the whole point of this project is that you can read it. One
ThreadingHTTPServer, a handful of routes, one static folder, SSE for streaming.
No framework, no build step, no node_modules.

Routes
    GET    /                       the app
    GET    /api/stats              notes, sessions, model
    GET    /api/sessions           list
    POST   /api/sessions           create
    GET    /api/sessions/<id>      one session + its messages
    PATCH  /api/sessions/<id>      rename / change mode
    DELETE /api/sessions/<id>
    POST   /api/chat               {session_id, message} -> text/event-stream
"""

from __future__ import annotations

import errno
import json
import re
import sys
import threading
import time
import webbrowser
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import activity
import artifacts
import fstools
import librarian
import memory
import models
import modes
import orchestrator
import profiles
import registry
import skills
import workspace
from config import FRONTIER_READY, MODEL, WHERE
from llm import stream_chat
from main import build_system, tool_definitions

WEB = Path(__file__).parent / "web"
PORT = 7777
BROWSER_CLOSE_GRACE = 3.0
BROWSER_IDLE_TIMEOUT = 180.0
BROWSER_OPEN_TIMEOUT = 30.0


class BrowserLease:
    """Tracks whether the browser that owns an auto-opened server is alive."""

    def __init__(self, now: float | None = None) -> None:
        self._lock = threading.Lock()
        self.started = time.monotonic() if now is None else now
        self.last_seen: float | None = None
        self.close_requested: float | None = None

    def heartbeat(self, now: float | None = None) -> None:
        with self._lock:
            self.last_seen = time.monotonic() if now is None else now
            self.close_requested = None

    def close(self, now: float | None = None) -> None:
        with self._lock:
            if self.last_seen is not None:
                self.close_requested = time.monotonic() if now is None else now

    def should_stop(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        with self._lock:
            if self.last_seen is None:
                return current - self.started >= BROWSER_OPEN_TIMEOUT
            if self.close_requested is not None:
                return current - self.close_requested >= BROWSER_CLOSE_GRACE
            return current - self.last_seen >= BROWSER_IDLE_TIMEOUT


class AtlasHTTPServer(ThreadingHTTPServer):
    browser_lease: BrowserLease | None = None


# ---------------------------------------------------------------- agent


PENDING_PERMISSIONS: dict[str, tuple[threading.Event, bool | None]] = {}


def _request_permission(tool: str, args: dict, call_id: str) -> str:
    token = uuid.uuid4().hex
    PENDING_PERMISSIONS[token] = (threading.Event(), None)
    return token


def decide_permission(token: str, allow: bool) -> bool:
    item = PENDING_PERMISSIONS.get(token)
    if not item:
        return False
    event, _ = item
    PENDING_PERMISSIONS[token] = (event, bool(allow))
    event.set()
    return True


def _tool_round(messages: list[dict], session_id: str, user_text: str, model: str | None = None):
    """One streaming assistant turn. Yields deltas, returns (text, calls)."""
    content = ""
    calls: dict[int, dict] = {}
    for chunk in stream_chat(messages, tool_definitions(), model=model):
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            content += delta.content
            yield ("delta", {"text": delta.content})
        for tc in delta.tool_calls or []:
            slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function:
                if tc.function.name:
                    slot["name"] += tc.function.name
                if tc.function.arguments:
                    slot["arguments"] += tc.function.arguments
    return content, list(calls.values())


def stream_turn(session_id: str, user_text: str, mode: str, model: str | None = None):
    """SSE generator: delta / tool / skill / artifact / permission / done / error."""
    history = memory.load_recent(24, session_id)

    skill_id = skills.select_skill(user_text)
    role = orchestrator.select_role(user_text)
    messages: list[dict] = [
        {"role": "system", "content": build_system(mode, user_text, skill_id)}
    ]
    messages += history
    messages.append({"role": "user", "content": user_text})
    memory.log_turn("user", user_text, mode, session_id)

    if skill_id:
        skill = skills.load_skill(skill_id)
        if skill:
            yield ("skill", {"id": skill_id, "name": skill["name"], "role": role})

    personal = re.search(
        r"who am i|my name|what do i study|what do i know about me|my sport|my project",
        user_text.lower(),
    )
    user = profiles.active()
    if personal and not profiles.list_all(user) and not memory.note_paths():
        answer = ("I don't have any saved memories for this profile yet. "
                  "Tell me about yourself and I'll remember it.")
        yield ("delta", {"text": answer})
        memory.log_turn("assistant", answer, mode, session_id)
        yield ("done", {"session": session_id, "text": answer})
        return

    used = profiles.search(profiles.active(), user_text, k=4)
    if used:
        yield ("memory", {
            "count": len(used),
            "categories": sorted({row["category"] for row in used}),
        })
    memory.update_session(session_id, mode=mode)
    if not history:
        memory.update_session(session_id, title=user_text[:70])

    answer_parts: list[str] = []
    fetched_for_skill = False
    git_prompts: set[str] = set()
    try:
        for _ in range(4):  # bounded multi-tool loop
            content, calls = yield from _tool_round(messages, session_id, user_text, model)
            if not calls:
                answer_parts.append(content)
                break

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {"id": c["id"] or f"call_{i}", "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                    for i, c in enumerate(calls)
                ],
            })

            for i, call in enumerate(calls):
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                call_id = call["id"] or f"call_{i}"
                level = registry.permission(call["name"], args)
                approved = level != "ASK"
                if not approved:
                    token = _request_permission(call["name"], args, call_id)
                    yield ("permission", {
                        "token": token, "tool": call["name"], "call_id": call_id,
                        "preview": json.dumps(args, ensure_ascii=False)[:220],
                    })
                    event, _ = PENDING_PERMISSIONS[token]
                    event.wait(120)
                    _, decision = PENDING_PERMISSIONS.pop(token, (event, None))
                    approved = decision is True

                if not approved:
                    tool_text = "Permission denied by user."
                    yield ("tool", {"name": call["name"], "result": tool_text,
                                    "ok": False, "status": "denied"})
                else:
                    result = registry.run(call["name"], args, approved=True)
                    if call["name"] == "web_fetch":
                        fetched_for_skill = True
                    if call["name"] == "git_status" and "diff" not in git_prompts:
                        git_prompts.add("diff")
                    tool_text = registry.content(result)
                    yield ("tool", {
                        "name": call["name"], "result": tool_text,
                        "ok": result["ok"], "status": "ok" if result["ok"] else "error",
                        "duration_ms": result["duration_ms"],
                        "args": json.dumps(args, ensure_ascii=False)[:220],
                    })
                    hint = result.get("artifact_hint")
                    if result["ok"] and hint:
                        item = artifacts.register(
                            hint.get("title", call["name"]), hint.get("kind", "file"),
                            path=hint.get("path"), chat_id=session_id,
                        )
                        yield ("artifact", item)

                messages.append({
                    "role": "tool", "tool_call_id": call_id, "content": tool_text,
                })
                if (skill_id == "web-research" and call["name"] == "web_search"
                        and not fetched_for_skill and result["ok"]):
                    messages.append({
                        "role": "user",
                        "content": "Follow the active skill: call web_fetch on the first result URL now, before answering.",
                    })
                if skill_id == "github-engineer" and result["ok"]:
                    if call["name"] == "git_status" and "diff" not in git_prompts:
                        git_prompts.add("diff")
                        messages.append({"role": "user", "content":
                            "Follow the active skill: call git_diff now before answering."})
                    elif call["name"] not in ("git_status", "git_diff") and "status" not in git_prompts:
                        git_prompts.add("status")
                        messages.append({"role": "user", "content":
                            "Follow the active skill: call git_status and git_diff now before answering."})
        else:
            from llm import chat as plain
            msg = plain(messages, None, model=model)
            if msg.content:
                answer_parts.append(msg.content)
                yield ("delta", {"text": msg.content})

        answer = "".join(answer_parts).strip() or "(no answer)"
        memory.log_turn("assistant", answer, mode, session_id)
        memory.update_session(session_id)
        yield ("done", {"session": session_id, "text": answer})
        threading.Thread(target=_journal, args=(user_text,), daemon=True).start()
    except Exception as exc:
        traceback.print_exc()
        yield ("error", {"message": f"{type(exc).__name__}: {exc}"})


def _journal(user_text: str) -> None:
    try:
        for fact in librarian.extract(user_text):
            user = profiles.active()
            if not memory.find_note(fact):
                memory.remember(fact, ["auto"])
            profiles.add(
                user, profiles.infer_category(fact), fact,
                source="user statement", confidence=0.75,
            )
    except Exception:
        pass


# ---------------------------------------------------------------- http


class Handler(BaseHTTPRequestHandler):
    server_version = "atlas"

    def log_message(self, *args):  # keep the terminal quiet
        pass

    # -- helpers -------------------------------------------------

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _sse(self, event: str, data: dict):
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        self.wfile.write(payload.encode())
        self.wfile.flush()

    # -- routing -------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/":
                return self._file(WEB / "index.html")
            if path in {"/app.js", "/style.css"}:
                return self._file(WEB / path.lstrip("/"))
            if path == "/api/stats":
                current = models.load()
                return self._json({
                    **memory.stats(),
                    "model": current["model"],
                    "where": current["base_url"],
                    "frontier": FRONTIER_READY,
                    "modes": list(modes.MODES),
                })
            if path == "/api/profiles":
                return self._json({
                    "profiles": profiles.list_profiles(),
                    "active": profiles.active(),
                })
            if path == "/api/memories":
                category = (parse_qs(urlparse(self.path).query).get("category") or [None])[0]
                return self._json({
                    "profile": profiles.active(),
                    "memories": profiles.list_all(profiles.active(), category),
                    "categories": sorted(profiles.CATEGORIES),
                })
            if path == "/api/memories/export":
                return self._json(profiles.export(profiles.active()))
            if path == "/api/models":
                query = parse_qs(urlparse(self.path).query)
                other = (query.get("base_url") or [None])[0]
                if other:
                    return self._json({
                        "base_url": other,
                        "model": models.load()["model"],
                        "models": models.list_models(other, ""),
                        "reachable": bool(models.list_models(other, "")),
                    })
                return self._json(models.describe())
            if path == "/api/tools":
                return self._json({"tools": registry.metadata()})
            if path == "/api/tools/activity":
                return self._json({"activity": registry.activity(300)})
            if path == "/api/permissions":
                return self._json({
                    "tools": {t["id"]: t["permission"] for t in registry.metadata()}
                })
            if path == "/api/skills":
                return self._json({"skills": skills.list_skills()})
            if path.startswith("/api/skills/"):
                item = skills.load_skill(unquote(path.split("/")[3]))
                return self._json({"skill": item} if item else {"error": "no such skill"},
                                  200 if item else 404)
            if path == "/api/workspace":
                return self._json(workspace.context())
            if path == "/api/artifacts":
                return self._json({"artifacts": artifacts.list_all()})
            if path.startswith("/api/artifacts/"):
                parts = path.split("/")
                artifact_id = unquote(parts[3])
                if len(parts) > 4 and parts[4] == "content":
                    file = artifacts.content_path(artifact_id)
                    if not file:
                        return self._json({"error": "no file content"}, 404)
                    data = file.read_bytes()
                    ctype = {
                        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".gif": "image/gif", ".svg": "image/svg+xml",
                        ".json": "application/json", ".md": "text/markdown",
                    }.get(file.suffix.lower(), "text/plain")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                item = artifacts.get(artifact_id)
                return self._json({"artifact": item} if item else {"error": "no such artifact"},
                                  200 if item else 404)
            if path == "/api/runtimes":
                return self._json({
                    "runtimes": models.scan_runtimes(),
                    "current": models.load()["base_url"],
                })
            if path == "/api/sessions":
                return self._json({"sessions": memory.list_sessions()})
            if path.startswith("/api/sessions/"):
                sid = unquote(path.split("/")[3])
                if not memory.session_exists(sid):
                    return self._json({"error": "no such session"}, 404)
                session = memory.get_session(sid)
                return self._json({
                    "session": session,
                    "messages": memory.session_messages(sid),
                })
            return self._json({"error": "not found"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._json({"error": str(exc)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()
        try:
            if path == "/api/lifecycle":
                if self.server.browser_lease:
                    self.server.browser_lease.heartbeat()
                return self._json({"ok": True})

            if path == "/api/lifecycle/close":
                if self.server.browser_lease:
                    self.server.browser_lease.close()
                return self._json({"ok": True}, 202)

            if path == "/api/profiles":
                action = body.get("action") or "switch"
                if action == "create":
                    profile_id = profiles.create(body.get("name", ""))
                    profiles.switch(profile_id)
                    return self._json({"id": profile_id}, 201)
                profiles.switch(body.get("id", ""))
                return self._json({"ok": True, "active": profiles.active()})

            if path == "/api/memories":
                memory_id, status = profiles.add(
                    profiles.active(),
                    body.get("category", "temporary"),
                    body.get("content", ""),
                    confidence=float(body.get("confidence", 0.7)),
                )
                return self._json({"id": memory_id, "status": status}, 201)
            if path == "/api/memories/import":
                saved = 0
                for item in body.get("items", []):
                    try:
                        profiles.add(
                            profiles.active(), item.get("category", "temporary"),
                            item.get("content", ""), source=item.get("source", "import"),
                            confidence=float(item.get("confidence", 0.6)),
                            created=item.get("created"),
                        )
                        saved += 1
                    except ValueError:
                        continue
                return self._json({"ok": True, "saved": saved})
            if path == "/api/memories/clear":
                return self._json({"deleted": profiles.clear(profiles.active())})

            if path == "/api/tools/permission":
                ok = decide_permission(body.get("token", ""), body.get("allow") is True)
                return self._json({"ok": ok})
            if path == "/api/permissions":
                try:
                    level = registry.set_permission(body.get("id", ""), body.get("permission", ""))
                except ValueError as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._json({"ok": True, "permission": level})
            if path == "/api/tools/config":
                try:
                    workspace = fstools.configure_workspace(body.get("workspace", ""))
                except fstools.ToolError as exc:
                    return self._json({"error": str(exc)}, 400)
                return self._json({"ok": True, "workspace": workspace})

            if path == "/api/settings":
                saved = models.save(
                    base_url=body.get("base_url", ""),
                    api_key=body.get("api_key", ""),
                    model=body.get("model", ""),
                )
                return self._json({"ok": True, **models.describe(), "saved": saved})

            if path == "/api/sessions":
                mode = modes.canonical(body.get("mode") or "")
                sid = memory.create_session(mode=mode, model=body.get("model"))
                return self._json({"id": sid}, 201)

            if path == "/api/models/pull":
                name = (body.get("model") or "").strip()
                if not name:
                    return self._json({"error": "which model?"}, 400)

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                try:
                    for event in models.pull(name):
                        if event.get("error"):
                            self._sse("error", {"message": event["error"]})
                            return
                        self._sse("pull", {
                            "status": event.get("status", ""),
                            "completed": event.get("completed") or 0,
                            "total": event.get("total") or 0,
                        })
                    self._sse("done", {"model": name, "models": models.describe()["models"]})
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as exc:
                    self._sse("error", {"message": str(exc)})
                return

            if path == "/api/chat":
                sid = body.get("session_id") or ""
                text = (body.get("message") or "").strip()
                if not memory.session_exists(sid):
                    return self._json({"error": "no such session"}, 404)
                if not text:
                    return self._json({"error": "empty message"}, 400)

                session = memory.get_session(sid) or {}
                mode = modes.canonical(body.get("mode") or session.get("mode") or "")
                model = body.get("model") or session.get("model") or None
                if body.get("model"):
                    memory.update_session(sid, model=body["model"])

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                try:
                    for event, data in stream_turn(sid, text, mode, model):
                        self._sse(event, data)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # user hit stop
                return

            return self._json({"error": "not found"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._json({"error": str(exc)}, 500)

    def do_PATCH(self):
        path = urlparse(self.path).path
        body = self._body()
        if path.startswith("/api/memories/"):
            try:
                memory_id = int(unquote(path.split("/")[3]))
                updated = profiles.update(
                    memory_id, profiles.active(), body.get("content"),
                    category=body.get("category"),
                )
                return self._json({"memory": updated})
            except (ValueError, TypeError) as exc:
                return self._json({"error": str(exc)}, 400)
        if not path.startswith("/api/sessions/"):
            return self._json({"error": "not found"}, 404)
        sid = unquote(path.split("/")[3])
        if not memory.session_exists(sid):
            return self._json({"error": "no such session"}, 404)
        try:
            memory.update_session(sid, title=body.get("title"), mode=body.get("mode"), model=body.get("model"))
            return self._json({"ok": True})
        except Exception as exc:
            return self._json({"error": str(exc)}, 400)

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/artifacts/"):
            return self._json({"ok": artifacts.delete(unquote(path.split("/")[3]))})
        if path.startswith("/api/memories/"):
            try:
                memory_id = int(unquote(path.split("/")[3]))
            except ValueError:
                return self._json({"error": "bad memory id"}, 400)
            return self._json({"ok": profiles.forget(memory_id, profiles.active())})
        if not path.startswith("/api/sessions/"):
            return self._json({"error": "not found"}, 404)
        sid = unquote(path.split("/")[3])
        try:
            memory.delete_session(sid)
            return self._json({"ok": True})
        except ValueError as exc:
            return self._json({"error": str(exc)}, 400)

    # -- static --------------------------------------------------

    def _file(self, path: Path):
        if not path.exists():
            return self._json({"error": "not found"}, 404)
        data = path.read_bytes()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(path.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _watch_browser(server: AtlasHTTPServer, lease: BrowserLease) -> None:
    while not lease.should_stop():
        time.sleep(1)
    print("\n  browser closed · stopping localhost server")
    server.shutdown()


def main() -> int:
    global PORT
    args = sys.argv[1:]
    if "--port" in args:
        PORT = int(args[args.index("--port") + 1])

    open_browser = "--open" in args
    exit_with_browser = open_browser and "--stay-open" not in args

    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    try:
        server = AtlasHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"atlas web is already using http://localhost:{PORT}")
        print(f"  inspect: lsof -nP -iTCP:{PORT} -sTCP:LISTEN")
        print("  stop the listed PID with: kill <PID>")
        return 1
    if exit_with_browser:
        server.browser_lease = BrowserLease()
        threading.Thread(
            target=_watch_browser,
            args=(server, server.browser_lease),
            daemon=True,
        ).start()

    print(f"atlas web · http://localhost:{PORT} · {MODEL}")
    if exit_with_browser:
        print("  closes automatically with the browser · ctrl-c also stops it")
    else:
        print("  ctrl-c to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
