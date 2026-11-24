"""Tests for the bounded code-action planner and high reasoning budget."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import agent  # noqa: E402
import config  # noqa: E402
import fstools  # noqa: E402
import llm  # noqa: E402
import main  # noqa: E402
import registry  # noqa: E402


class ReasoningBudget(unittest.TestCase):
    def test_reasoning_models_get_high_ceiling(self):
        self.assertEqual(llm._budget("deepseek-r1:7b"), config.REASONING_TOKENS)
        self.assertEqual(llm._budget("qwq:32b"), config.REASONING_TOKENS)
        self.assertEqual(llm._budget("qwen2.5-coder:7b"), config.MAX_TOKENS)
        self.assertGreaterEqual(config.REASONING_TOKENS, 4096)


class WorkspaceDefault(unittest.TestCase):
    def test_fresh_clone_has_a_confined_workspace(self):
        with patch.object(fstools, "CONFIG_FILE", ROOT / "data" / "no-tools.json"), \
             patch.dict("os.environ", {}, clear=False):
            os_environ = dict(__import__("os").environ)
            os_environ.pop("ATLAS_WORKSPACE", None)
            with patch.dict("os.environ", os_environ, clear=True):
                self.assertEqual(fstools.workspace(), config.ROOT)
                self.assertTrue(fstools.status()["available"])


class Planner(unittest.TestCase):
    def test_intent_detection(self):
        self.assertTrue(agent.needs_actions("Create a Python file that sorts a list"))
        self.assertTrue(agent.needs_actions("Fix the bug in main.py"))
        self.assertFalse(agent.needs_actions("What is a list comprehension?"))
        self.assertFalse(agent.needs_actions("Tell me about the Roman Empire"))

    def test_plan_validates_and_bounds_actions(self):
        payload = json.dumps({"actions": [
            {"tool": "files", "args": {"action": "write", "path": "demo/x.py", "content": "x=1\n"}},
            {"tool": "files", "args": {"action": "write", "path": "/etc/passwd", "content": "x"}},
            {"tool": "files", "args": {"action": "delete", "path": "x.py"}},
            {"tool": "terminal", "args": {"command": "ls; rm -rf /"}},
            {"tool": "unknown", "args": {}},
        ], "answer": "wrote demo/x.py"})
        with patch.object(agent, "chat", return_value=SimpleNamespace(content=payload)):
            plan = agent.plan("Create demo/x.py with x=1")
        self.assertEqual(plan["answer"], "wrote demo/x.py")
        self.assertEqual(len(plan["actions"]), 1)
        self.assertEqual(plan["actions"][0]["args"]["path"], "demo/x.py")

    def test_execute_uses_registry(self):
        with patch.object(registry, "run", return_value={
            "tool": "files", "ok": True, "data": "saved", "error": None, "duration_ms": 1,
        }):
            done = agent.execute([{"tool": "files", "args": {"action": "read", "path": "README.md"}}])
        self.assertEqual(done[0]["text"], "saved")
        self.assertTrue(done[0]["ok"])


class AgentLoop(unittest.TestCase):
    def test_code_request_executes_one_plan_then_answers(self):
        patches = [
            patch.object(main, "build_system", return_value="system"),
            patch.object(main.memory, "log_turn"),
            patch.object(main.memory, "cli_session", return_value="cli"),
            patch.object(main, "journal"),
            patch.object(agent, "plan", return_value={
                "actions": [{"tool": "files", "args": {
                    "action": "write", "path": "demo/x.py", "content": "x = 1\n"}}],
                "answer": "wrote demo/x.py",
            }),
        ]
        for item in patches:
            item.start()
        try:
            replies = [
                SimpleNamespace(content="I'll create that file.", tool_calls=None),
                SimpleNamespace(content="Created demo/x.py with x = 1.", tool_calls=None),
            ]
            used = []

            def run(tool, args=None, **kwargs):
                used.append((tool, args))
                return {"tool": tool, "ok": True, "data": "saved", "error": None,
                        "duration_ms": 1}

            with patch.dict(os.environ, {"ATLAS_USE_GOALRUNNER": "0"}), \
                 patch.object(main, "chat", side_effect=replies), \
                 patch.object(agent, "execute", side_effect=lambda actions: [
                     {"id": "plan_0", "name": a["tool"], "args": a["args"],
                      "text": "saved", "ok": True} for a in actions
                 ]):
                answer = main.turn(
                    [{"role": "system", "content": ""}],
                    "Create a Python file demo/x.py with x = 1",
                    "general", write_memory=False,
                )
            self.assertIn("Created", answer)
            self.assertEqual(agent.plan.call_count, 1)
        finally:
            for item in reversed(patches):
                item.stop()


if __name__ == "__main__":
    unittest.main()
