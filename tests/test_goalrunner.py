"""Tests for goal-driven multi-tool execution and local learning."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import examples  # noqa: E402
import goalrunner as gr  # noqa: E402
import toolpolicy as tp  # noqa: E402


class Policy(unittest.TestCase):
    def test_intent_and_signature(self):
        self.assertEqual(tp.intent("fix the python file parser"), "code")
        self.assertEqual(tp.intent("search the web for news"), "web")
        self.assertEqual(tp.intent("Apple revenue last quarter"), "company")
        sig = tp.signature("Create a Python file that parses notes")
        self.assertTrue(sig.startswith("code|"))
        self.assertIn("python", sig)
        other = tp.signature("create python file that parse notes")
        self.assertEqual(sig.split("|")[0], other.split("|")[0])
        self.assertIn("python", other)

    def test_online_learning_and_deterministic_rank(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(tp, "DB", Path(tmp) / "policy.db"):
                sig = "code|python notes"
                tp.record(sig, "files", True, 100)
                tp.record(sig, "files", True, 150)
                tp.record(sig, "terminal", False, 20)
                stats = {row["tool"]: row for row in tp.stats(sig)}
                self.assertEqual(stats["files"]["n"], 2)
                self.assertEqual(stats["files"]["success"], 2)
                self.assertEqual(stats["terminal"]["success"], 0)
                self.assertGreater(stats["files"]["mean"], stats["terminal"]["mean"])
                ranked = tp.rank(["terminal", "files", "web_search"], sig, explore=0)
                self.assertEqual(ranked[0], "files")
                self.assertIn("web_search", ranked)
                self.assertIn("files", tp.prompt_hint(sig))

    def test_examples_retrieve_similar_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(examples, "DB", Path(tmp) / "examples.db"), \
                 patch.object(tp, "DB", Path(tmp) / "policy.db"):
                examples.save(
                    "Create a Python script that parses notes and writes a report",
                    [{"tool": "files", "args": {"action": "write", "path": "a.py"}}],
                )
                found = examples.similar("write a Python script to parse notes and report")
                self.assertTrue(found)
                self.assertEqual(found[0]["steps"][0]["tool"], "files")
                self.assertIn("files", examples.prompt_hint("write a Python script"))


class Validation(unittest.TestCase):
    def test_valid_step(self):
        clean, error = gr._validate_step({
            "tool": "files",
            "args": {"action": "read", "path": "notes.md"},
        })
        self.assertFalse(error)
        self.assertEqual(clean["tool"], "files")

    def test_unsafe_and_unknown_steps(self):
        for step in (
            {"tool": "shell", "args": {"command": "ls"}},
            {"tool": "files", "args": {"action": "read", "path": "../etc/passwd"}},
            {"tool": "files", "args": {"action": "read", "path": "/etc/passwd"}},
            {"tool": "terminal", "args": {"command": "ls; rm -rf /"}},
            {"tool": "files", "args": {"action": "write", "path": "bad.py",
                                        "content": "def broken(:"}},
        ):
            clean, error = gr._validate_step(step)
            self.assertIsNone(clean)
            self.assertTrue(error)

    def test_rule_plan_and_goal_check(self):
        goal = "Create demo/x.py with a script that prints RULE_OK, then run it"
        steps = gr.rule_plan(goal)
        self.assertEqual([step["tool"] for step in steps], ["files", "terminal"])
        self.assertIn("RULE_OK", steps[0]["args"]["content"])
        self.assertEqual(steps[1]["args"]["command"], "python demo/x.py")
        self.assertFalse(gr.goal_satisfied(goal, [])[0])
        self.assertTrue(gr.goal_satisfied(goal, [
            {"tool": "files", "args": {"action": "write", "path": "demo/x.py"},
             "text": "Wrote demo/x.py", "ok": True},
            {"tool": "terminal", "args": {"command": "python demo/x.py"},
             "text": "RULE_OK", "ok": True},
        ])[0])

    def test_command_normalisation(self):
        self.assertEqual(gr.normalise_command("demo/x.py"), "python demo/x.py")
        self.assertEqual(gr.normalise_command("git_status"), "git status")
        self.assertEqual(gr.normalise_command("uv python demo/x.py"),
                         "uv run python demo/x.py")

    def test_budget_scales_with_goal(self):
        simple = gr.adaptive_budget("list files")
        complex_goal = gr.adaptive_budget(
            "write a parser, read the notes, then run the test and verify output"
        )
        self.assertGreaterEqual(complex_goal, simple)
        self.assertLessEqual(complex_goal, 8)


class Runner(unittest.TestCase):
    def test_multi_step_run_reaches_goal(self):
        plan = {
            "steps": [
                {"tool": "files", "args": {"action": "write", "path": "a.md",
                                           "content": "hello"}, "why": "create"},
                {"tool": "files", "args": {"action": "read", "path": "a.md"},
                 "why": "verify"},
            ],
            "done_when": "file exists and contains hello",
        }
        check = {"done": True, "reason": "file verified", "next": []}
        outcomes = [
            {"tool": "files", "args": plan["steps"][0]["args"], "ok": True,
             "text": "saved", "duration_ms": 5},
            {"tool": "files", "args": plan["steps"][1]["args"], "ok": True,
             "text": "hello", "duration_ms": 4},
        ]
        with patch.object(gr, "_ask", side_effect=[plan, check]), \
             patch.object(gr, "rule_plan", return_value=[]), \
             patch.object(gr, "_execute", side_effect=outcomes), \
             patch.object(gr, "_final_report", return_value="Created and verified a.md."), \
             patch.object(gr.toolpolicy, "record"), \
             patch.object(gr.examples, "save"):
            events = []
            result = gr.run("Create a.md and verify it", on_event=events.append)
        self.assertTrue(result["done"])
        self.assertEqual(result["step_count"], 2)
        self.assertEqual(result["tools_used"], ["files"])
        self.assertTrue(any(event.get("status") == "done" for event in events))
        self.assertIn("Created", result["answer"])

    def test_failed_step_does_not_crash(self):
        plan = {"steps": [
            {"tool": "files", "args": {"action": "read", "path": "missing.md"}}
        ], "done_when": "file read"}
        check = {"done": False, "reason": "blocked", "next": []}
        outcome = {"tool": "files", "args": plan["steps"][0]["args"], "ok": False,
                   "text": "not found", "duration_ms": 3}
        with patch.object(gr, "_ask", side_effect=[plan, {"steps": []}, check]), \
             patch.object(gr, "rule_plan", return_value=[]), \
             patch.object(gr, "_execute", return_value=outcome), \
             patch.object(gr.toolpolicy, "record"), \
             patch.object(gr.examples, "save"):
            result = gr.run("read missing.md")
        self.assertFalse(result["done"])
        self.assertEqual(result["step_count"], 1)
        self.assertEqual(result["reason"], "blocked")


if __name__ == "__main__":
    unittest.main()
