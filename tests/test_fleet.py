"""Shared drive, fleet controller and local→frontier bridge."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bridge  # noqa: E402
import fleet  # noqa: E402
import goalrunner as gr  # noqa: E402
import sharetools  # noqa: E402


class SharedDrive(unittest.TestCase):
    def test_write_read_handoff_and_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"ATLAS_SHARED_DRIVE": tmp,
                                         "ATLAS_PROFILE": "tester"}):
                self.assertIn("Wrote", sharetools.run({
                    "action": "write", "path": "a.txt", "content": "shared-data"}))
                self.assertIn("shared-data", sharetools.run({
                    "action": "read", "path": "a.txt"}))
                sharetools.run({"action": "handoff", "note": "HELLO_AGENT"})
                self.assertIn("HELLO_AGENT", sharetools.run({
                    "action": "read", "path": sharetools.HANDOFF}))
                with self.assertRaises(Exception):
                    sharetools.run({"action": "read", "path": "../secret"})

    def test_rule_plan_uses_shared_drive(self):
        steps = gr.rule_plan(
            "Create shared file notes/shared.md containing SHARED_OK"
        )
        self.assertEqual(steps[0]["tool"], "share")
        self.assertIn("SHARED_OK", steps[0]["args"]["content"])
        self.assertEqual(len(steps), 1)  # no terminal for a shared note


class Bridge(unittest.TestCase):
    def test_unconfigured_frontier_is_explicit(self):
        with patch.object(bridge.config, "FRONTIER_READY", False):
            result = bridge.run("hello")
        self.assertFalse(result["ok"])
        self.assertIn("frontier tier is not configured", result["error"])

    def test_local_brief_then_frontier_answer(self):
        def fake_chat(messages, tools=None, **opts):
            class Reply:
                content = ""
            if opts.get("tier") == "local":
                Reply.content = '{"goal":"find the number","what_matters":["number"],' \
                                '"missing":"estimate","instructions":"be direct"}'
            else:
                Reply.content = "About 2,000 words."
            return Reply()

        with patch.object(bridge.config, "FRONTIER_READY", True), \
             patch.object(bridge.llm, "chat", side_effect=fake_chat):
            result = bridge.run("how many French words are in Russian?")
        self.assertTrue(result["ok"])
        self.assertEqual(result["brief"]["goal"], "find the number")
        self.assertIn("2,000", result["answer"])


class Fleet(unittest.TestCase):
    def test_create_and_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "fleet.json"
            with patch.object(fleet, "FLEET", store), \
                 patch.object(fleet.orchestrator, "INSTANCES_FILE",
                              Path(tmp) / "instances.json"), \
                 patch.dict(os.environ, {"ATLAS_SHARED_DRIVE": tmp}):
                row = fleet.create("Worker", tmp, "ollama", "qwen2.5:3b")
                self.assertEqual(row["status"], "stopped")
                self.assertGreaterEqual(row["port"], fleet.BASE_PORT)
                rows = fleet.list_instances()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["label"], "Worker")
                self.assertTrue(fleet.remove(row["id"]))

    def test_orchestrate_collects_agents_without_frontier(self):
        goal = "Write a note"
        running = [{"id": "x", "label": "A", "status": "running", "port": 7800}]
        with patch.object(fleet, "list_instances", return_value=running), \
             patch.object(fleet.sharetools, "run", return_value="ok"), \
             patch.object(fleet, "send_goal", return_value={
                 "id": "x", "label": "A", "ok": True, "answer": "done"}), \
             patch.object(bridge, "run", return_value={
                 "ok": False, "error": "no frontier"}):
            result = fleet.orchestrate(goal)
        self.assertEqual(result["agents"][0]["answer"], "done")
        self.assertIn("Local synthesis", result["synthesis"])


if __name__ == "__main__":
    unittest.main()
