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

import json
import sys
import threading
import webbrowser
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import activity
import librarian
import memory
import modes
from config import FRONTIER_READY, MODEL, WHERE
from llm import stream_chat
from main import TOOLS, build_system, run_tool

WEB = Path(__file__).parent / "web"
PORT = 7777


# ---------------------------------------------------------------- agent


def _tool_round(messages: list[dict], session_id: str, user_text: str):
    """One streaming assistant turn. Yields events, returns (text, tool_calls)."""
    content = ""
    calls: dict[int, dict] = {}

    for chunk in stream_chat(messages, TOOLS):
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


def stream_turn(session_id: str, user_text: str, mode: str):
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
            content, calls, err = yield from _tool_round(messages, session_id, user_text)
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

            msg = plain(messages, None)
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
                return self._json({
                    **memory.stats(),
                    "model": MODEL,
                    "where": WHERE,
                    "frontier": FRONTIER_READY,
                    "modes": list(modes.MODES),
                })
            if path == "/api/sessions":
                return self._json({"sessions": memory.list_sessions()})
            if path.startswith("/api/sessions/"):
                sid = unquote(path.split("/")[3])
                if not memory.session_exists(sid):
                    return self._json({"error": "no such session"}, 404)
                session = next((s for s in memory.list_sessions() if s["id"] == sid), None)
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
            if path == "/api/sessions":
                mode = body.get("mode") or "coach"
                sid = memory.create_session(mode=mode)
                return self._json({"id": sid}, 201)

            if path == "/api/chat":
                sid = body.get("session_id") or ""
                text = (body.get("message") or "").strip()
                if not memory.session_exists(sid):
                    return self._json({"error": "no such session"}, 404)
                if not text:
                    return self._json({"error": "empty message"}, 400)

                session = next((s for s in memory.list_sessions() if s["id"] == sid), {})
                mode = body.get("mode") or session.get("mode") or "coach"

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()

                try:
                    for event, data in stream_turn(sid, text, mode):
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
            memory.update_session(sid, title=body.get("title"), mode=body.get("mode"))
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


def main() -> None:
    global PORT
    args = sys.argv[1:]
    if "--port" in args:
        PORT = int(args[args.index("--port") + 1])

    if "--open" in args:
        threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()

    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"atlas web · http://localhost:{PORT} · {MODEL}")
    print("  ctrl-c to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
