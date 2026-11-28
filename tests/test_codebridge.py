"""Frontier code writing and tournament selection."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import codebridge  # noqa: E402
import fleet  # noqa: E402


class CodeBridge(unittest.TestCase):
    def test_unconfigured_frontier_is_explicit(self):
        with patch.object(codebridge.config, "FRONTIER_READY", False):
            result = codebridge.run("write a script")
        self.assertFalse(result["ok"])
        self.assertIn("frontier tier is not configured", result["error"])

    def test_local_spec_then_frontier_code_is_written_and_checked(self):
        class Reply:
            def __init__(self, content):
                self.content = content

        spec = json.dumps({"goal": "print a marker", "language": "python",
                           "files": ["demo/x.py"], "constraints": [],
                           "verify": "python demo/x.py"})
        code = json.dumps({"files": [
            {"path": "demo/x.py", "content": "print('CODE_OK')\n"},
            {"path": "../evil.py", "content": "print('bad')"},
        ], "notes": "done"})

        def fake_chat(messages, tools=None, **opts):
            return Reply(spec if opts.get("tier") == "local" else code)

        written = []
        with patch.object(codebridge.config, "FRONTIER_READY", True), \
             patch.object(codebridge.llm, "chat", side_effect=fake_chat), \
             patch.object(codebridge.fstools, "write",
                          side_effect=lambda path, content: written.append((path, content)) or "ok"), \
             patch.object(codebridge.termtools, "run", return_value="CODE_OK"):
            result = codebridge.run("write a script that prints CODE_OK", execute=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["brief"]["goal"], "print a marker")
        self.assertEqual(written[0][0], "demo/x.py")
        self.assertTrue(any(item["error"] for item in result["rejected"]))
        self.assertTrue(any("CODE_OK" in check for check in result["checks"]))
        self.assertEqual(result["frontier_model"], codebridge.config.FRONTIER_MODEL)


class Tournament(unittest.TestCase):
    def test_scoring_and_winner(self):
        goal = "Create a file printing TOURNEY_OK"
        agents = [
            {"id": "a", "label": "A", "ok": True,
             "answer": "Done.\n- TOURNEY_OK observed\nhttps://example.org"},
            {"id": "b", "label": "B", "ok": False, "answer": "(no answer)"},
        ]
        running = [{"id": "a", "label": "A", "status": "running", "port": 7800},
                   {"id": "b", "label": "B", "status": "running", "port": 7801}]
        with patch.object(fleet, "list_instances", return_value=running), \
             patch.object(fleet, "send_goal", side_effect=agents), \
             patch.object(fleet.sharetools, "run", return_value="ok"):
            result = fleet.tournament(goal)
        self.assertEqual(result["winner"], "A")
        self.assertEqual(result["results"][0]["score"] > result["results"][1]["score"], True)
        self.assertEqual(result["receipt"], "WINNER.md")


if __name__ == "__main__":
    unittest.main()
