"""Tests for goal state and isolation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import goals  # noqa: E402
import profiles  # noqa: E402


class Goals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(goals, "DB", Path(self.tmp.name) / "goals.db")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_create_progress_and_finish(self):
        goal = goals.create("Build a small Python app")
        self.assertEqual(goal["status"], "active")
        self.assertIn("GOAL: Build a small Python app", goals.block())
        updated = goals.update(goal["id"], "running", "wrote app.py")
        self.assertEqual(updated["status"], "running")
        self.assertEqual(json.loads(updated["notes"]), ["wrote app.py"])
        self.assertIn("wrote app.py", goals.block())
        done = goals.finish(goal["id"])
        self.assertEqual(done["status"], "done")
        self.assertEqual(goals.current(), None)

    def test_profile_isolation(self):
        first = goals.create("Alice objective", user="u-alice")
        with patch.object(profiles, "active", return_value="u-bob"):
            self.assertIsNone(goals.current())
            self.assertEqual(goals.list_all(), [])
            self.assertIsNone(goals.update(first["id"], "done", user="u-bob"))
        self.assertEqual(goals.current(user="u-alice")["id"], first["id"])

    def test_empty_goal_refused(self):
        with self.assertRaises(ValueError):
            goals.create("   ")


if __name__ == "__main__":
    unittest.main()
