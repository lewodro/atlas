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
import sys
import threading
import time
import webbrowser
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import activity
import librarian
import memory
import models
import modes
from config import FRONTIER_READY, MODEL, WHERE
from llm import stream_chat
from main import TOOLS, build_system, run_tool

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


def _tool_round(messages: list[dict], session_id: str, user_text: str, model: str | None = None):
    """One streaming assistant turn. Yields events, returns (text, tool_calls)."""
    content = ""
    calls: dict[int, dict] = {}

    for chunk in stream_chat(messages, TOOLS, model=model):
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

    return content, list(calls.values()), None


def stream_turn(session_id: str, user_text: str, mode: str, model: str | None = None):
    """SSE event generator: delta / tool / done / error."""
    history = memory.load_recent(24, session_id)

    messages: list[dict] = [{"role": "system", "content": build_system(mode, user_text)}]
    messages += history
    messages.append({"role": "user", "content": user_text})

    memory.log_turn("user", user_text, mode, session_id)
    memory.update_session(session_id, mode=mode)
    if not history:  # first message becomes the title
        memory.update_session(session_id, title=user_text[:70])

    answer_parts: list[str] = []

    try:
        for _ in range(2):
            content, calls, err = yield from _tool_round(messages, session_id, user_text, model)
            if err:
                yield ("error", {"message": err})
                return

            if not calls:
                answer_parts.append(content)
                break

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": c["id"] or f"call_{i}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                    }
                    for i, c in enumerate(calls)
                ],
            })

            for i, call in enumerate(calls):
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = run_tool(call["name"], args, user_text)
                yield ("tool", {"name": call["name"], "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"] or f"call_{i}",
                    "content": result,
                })
        else:
            # two tool rounds and still no prose: take the tools away
            from llm import chat as plain

            msg = plain(messages, None, model=model)
            text = msg.content or ""
            answer_parts.append(text)
            if text:
                yield ("delta", {"text": text})

        answer = "".join(answer_parts).strip() or "(no answer)"
        memory.log_turn("assistant", answer, mode, session_id)
        memory.update_session(session_id)
        yield ("done", {"session": session_id, "text": answer})

        # note-taking must not delay the UI or break the stream
        threading.Thread(
            target=_journal, args=(user_text,), daemon=True
        ).start()

    except Exception as exc:  # surface it, don't kill the server
        traceback.print_exc()
        yield ("error", {"message": f"{type(exc).__name__}: {exc}"})


def _journal(user_text: str) -> None:
    try:
        for fact in librarian.extract(user_text):
            if not memory.find_note(fact):
                memory.remember(fact, ["auto"])
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
            if path == "/api/models":
                return self._json(models.describe())
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

            if path == "/api/settings":
                saved = models.save(
                    base_url=body.get("base_url", ""),
                    api_key=body.get("api_key", ""),
                    model=body.get("model", ""),
                )
                return self._json({"ok": True, **models.describe(), "saved": saved})

            if path == "/api/sessions":
                mode = body.get("mode") or "coach"
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
                mode = body.get("mode") or session.get("mode") or "coach"
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
        if not path.startswith("/api/sessions/"):
            return self._json({"error": "not found"}, 404)
        sid = unquote(path.split("/")[3])
        if not memory.session_exists(sid):
            return self._json({"error": "no such session"}, 404)
        body = self._body()
        try:
            memory.update_session(sid, title=body.get("title"), mode=body.get("mode"), model=body.get("model"))
            return self._json({"ok": True})
        except Exception as exc:
            return self._json({"error": str(exc)}, 400)

    def do_DELETE(self):
        path = urlparse(self.path).path
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
