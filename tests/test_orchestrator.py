"""Tests for the unified agent, Study skill and orchestrator."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import modes  # noqa: E402
import orchestrator  # noqa: E402
import skills  # noqa: E402


class UnifiedMode(unittest.TestCase):
    def test_only_one_mode(self):
        self.assertEqual(list(modes.MODES), ["agent"])
        self.assertEqual(modes.DEFAULT, "agent")

    def test_old_names_are_aliases(self):
        for old in ("coach", "tutor", "review", "debug", "plan", "study"):
            self.assertEqual(modes.canonical(old), "agent")
            self.assertEqual(modes.get(old), modes.get("agent"))

    def test_build_does_not_mention_old_modes(self):
        prompt = modes.build("coach", "some note", "git log")
        for word in ("COACH mode", "TUTOR mode", "DEBUG mode", "PLAN mode", "REVIEW mode"):
            self.assertNotIn(word, prompt)
        self.assertIn("one unified AGENT mode", prompt)


class StudySkill(unittest.TestCase):
    def test_study_requests_select_study(self):
        for text in (
            "study this", "make notes on calculus", "summarize this",
            "draw the graph of a function", "explain this for an exam",
        ):
            with self.subTest(text=text):
                self.assertEqual(skills.select_skill(text), "study")

    def test_study_skill_is_lazy(self):
        item = skills.load_skill("study")
        self.assertIn("worked example", item["body"])
        self.assertNotIn("body", skills.list_skills()[0])


class Orchestrator(unittest.TestCase):
    def test_role_selection(self):
        cases = {
            "study the derivative": "study",
            "search the web for news": "research",
            "check the git diff": "engineer",
            "who am i": "memory",
            "hello there": "general",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(orchestrator.select_role(text), expected)

    def test_plan_is_bounded(self):
        result = orchestrator.plan("study and explain this function")
        self.assertEqual(result["role"], "study")
        self.assertLessEqual(len(result["skills"]), 2)

    def test_instances_are_local(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "instances.json"
            with patch.object(orchestrator, "INSTANCES_FILE", path):
                self.assertEqual(orchestrator.list_instances(), [])
                row = orchestrator.create_instance("Demo", "/tmp/demo")
                self.assertEqual(row["label"], "Demo")
                self.assertEqual(len(orchestrator.list_instances()), 1)
                self.assertTrue(orchestrator.remove_instance(row["id"]))
                self.assertEqual(orchestrator.list_instances(), [])


if __name__ == "__main__":
    unittest.main()
