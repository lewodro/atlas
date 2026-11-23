"""Tests for answer depth and sequential agent collaboration."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import depth  # noqa: E402
import dispatch  # noqa: E402
import fstools  # noqa: E402
import handoff  # noqa: E402
import registry  # noqa: E402
import reporttools  # noqa: E402


class Depth(unittest.TestCase):
    def test_long_signals(self):
        for text in ("Give me a detailed answer", "definitive research on X",
                     "help me build a game", "explain thoroughly"):
            with self.subTest(text=text):
                self.assertTrue(depth.is_long(text))
                self.assertIn("500-900", depth.instruction(text))

    def test_short_wins(self):
        self.assertFalse(depth.is_long("give me a brief answer"))


class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(self.tmp.name)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_write_then_read(self):
        result = handoff.write("tester", "Built app.py", ["app.py"])
        self.assertTrue(result["ok"])
        text = handoff.read()
        self.assertIn("tester", text)
        self.assertIn("app.py", text)
        second = handoff.write("coder", "Found a bug")
        self.assertTrue(second["ok"])
        self.assertIn("Found a bug", handoff.read())


class ReportTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(self.tmp.name)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_report_hands_back(self):
        result = reporttools.test_report("syntax OK", "none")
        self.assertTrue(result["ok"])
        text = Path(self.tmp.name, "HANDOFF.md").read_text()
        self.assertIn("coder", text)
        self.assertIn("syntax OK", text)


class Sequential(unittest.TestCase):
    def test_runs_in_order_and_passes_context(self):
        rows = [
            {"id": "w1", "label": "Builder", "role": "coder", "model": "a",
             "port": 1, "workspace": "/tmp/shared"},
            {"id": "w2", "label": "Tester", "role": "tester", "model": "b",
             "port": 2, "workspace": "/tmp/shared"},
        ]
        seen = []

        class Message:
            content = "combined"

        def fake_ask(wid, text, timeout=240):
            seen.append((wid, text))
            return {"worker": wid, "label": wid, "role": "coder", "model": "a",
                    "answer": f"report from {wid}", "tools": []}

        with patch.object(dispatch.workers, "list_workers", return_value=rows), \
             patch.object(dispatch.workers, "healthy", return_value=True), \
             patch.object(dispatch.workers, "ask", side_effect=fake_ask), \
             patch.object(dispatch.llm, "chat", return_value=Message()):
            result = dispatch.orchestrate(
                "build pacman", ["w1", "w2"],
                workspace="/tmp/shared", sequential=True,
            )
        self.assertEqual([wid for wid, _ in seen], ["w1", "w2"])
        self.assertIn("report from w1", seen[1][1])
        self.assertEqual(len(result["reports"]), 2)
        self.assertTrue(result["sequential"])


class Registry(unittest.TestCase):
    def test_handoff_registered(self):
        ids = {row["id"] for row in registry.metadata()}
        self.assertTrue({"handoff", "handoff_read"} <= ids)


if __name__ == "__main__":
    unittest.main()
