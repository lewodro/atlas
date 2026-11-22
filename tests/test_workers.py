"""Tests for local workers and orchestration (processes/network mocked)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import dispatch  # noqa: E402
import workers  # noqa: E402


class WorkerRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(workers, "FILE", Path(self.tmp.name) / "workers.json")
        self.patch.start()
        self.root = Path(self.tmp.name) / "ws"
        self.root.mkdir()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_create_and_remove(self):
        row = workers.create("Research", str(self.root), "qwen2.5:3b", "research")
        self.assertEqual(row["model"], "qwen2.5:3b")
        self.assertEqual(row["role"], "research")
        self.assertEqual(len(workers.list_workers()), 1)
        self.assertTrue(workers.remove(row["id"]))
        self.assertEqual(workers.list_workers(), [])

    def test_isolation_env(self):
        row = workers.create("Engineer", str(self.root), "qwen-local:latest", "engineer")
        env = workers.env_for(row)
        self.assertEqual(env["ATLAS_MODEL"], "qwen-local:latest")
        self.assertEqual(env["ATLAS_WORKSPACE"], str(self.root.resolve()))
        self.assertTrue(env["ATLAS_DATA_DIR"].endswith(row["id"]))
        self.assertTrue(env["ATLAS_NOTES_DIR"].endswith(row["id"] + "/notes"))

    def test_rejects_bad_role_and_duplicate_port(self):
        with self.assertRaises(ValueError):
            workers.create("Bad", str(self.root), role="hacker")
        workers.create("One", str(self.root), port=7801)
        with self.assertRaises(ValueError):
            workers.create("Two", str(self.root), port=7801)

    def test_ask_parses_sse_and_approves(self):
        row = workers.create("Research", str(self.root), "qwen2.5:3b", "research")
        chunks = [
            b'event: permission\ndata: {"token":"t1","tool":"files"}\n\n',
            b'event: tool\ndata: {"name":"files","status":"ok","result":"x"}\n\n',
            b'event: done\ndata: {"session":"s","text":"done"}\n\n',
        ]
        posts = []

        class Response:
            def __iter__(self):
                return iter(chunks)

        def fake_post(port, path, payload, timeout=240):
            posts.append((path, payload))
            if path == "/api/sessions":
                return io.StringIO('{"id":"s"}')
            return Response()

        session_file = Path(self.tmp.name) / "session.json"
        session_file.write_text('{"id":"s"}')
        with patch.object(workers, "get", return_value=row), \
             patch.object(workers, "healthy", return_value=True), \
             patch.object(workers, "_post", side_effect=fake_post):
            result = workers.ask(row["id"], "task")
        self.assertEqual(result["answer"], "done")
        self.assertEqual(result["tools"][0]["name"], "files")
        self.assertTrue(any(p == "/api/tools/permission" for p, _ in posts))


class Dispatch(unittest.TestCase):
    def test_orchestrate_uses_workers_and_synthesizes(self):
        rows = [
            {"id": "w1", "label": "Research", "role": "research", "model": "a", "port": 1},
            {"id": "w2", "label": "Engineer", "role": "engineer", "model": "b", "port": 2},
        ]

        class Message:
            content = "combined report"

        with patch.object(dispatch.workers, "list_workers", return_value=rows), \
             patch.object(dispatch.workers, "healthy", return_value=True), \
             patch.object(dispatch.workers, "ask", side_effect=lambda wid, text: {
                 "worker": wid, "label": wid, "role": "research", "model": "a",
                 "answer": f"report from {wid}", "tools": []}), \
             patch.object(dispatch.llm, "chat", return_value=Message()):
            result = dispatch.orchestrate("do the thing")
        self.assertEqual(result["answer"], "combined report")
        self.assertEqual(len(result["reports"]), 2)
        self.assertIn("do the thing", result["goal"])

    def test_empty_goal_refused(self):
        with self.assertRaises(ValueError):
            dispatch.orchestrate("")


if __name__ == "__main__":
    unittest.main()
