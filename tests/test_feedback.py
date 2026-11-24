"""Local feedback and learning-snapshot tests."""

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
import feedback  # noqa: E402
import toolpolicy as tp  # noqa: E402


class Signals(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(feedback.classify("That's wrong, try again"), -1)
        self.assertEqual(feedback.classify("Thanks, perfect"), 1)
        self.assertEqual(feedback.classify("What about the tests?"), 0)
        self.assertEqual(feedback.classify(""), 0)

    def test_heuristic_grade(self):
        low = feedback.grade("write a file", "(no answer)", "", "local")
        high = feedback.grade(
            "write a file", "Created demo/x.py and verified it. https://example.org/x",
            "1. files ok=True output=Wrote 14 chars", "local",
        )
        self.assertLess(low, high)
        self.assertLessEqual(high, 1.0)


class Learning(unittest.TestCase):
    def test_feedback_flow_updates_scores_and_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "atlas.db"
            with patch.object(tp, "DB", db), \
                 patch.object(examples, "DB", db), \
                 patch.object(feedback, "DB", db):
                goal = "Create a Python file and verify it"
                tools = [{"tool": "files"}, {"tool": "terminal"}]
                tp.record(tp.signature(goal), "files", True, 10)
                examples.save(goal, tools)
                score = feedback.finish(goal, tools, "Created and verified the file.",
                                        "files ok=True output=saved", "local")
                self.assertGreater(score, 0.5)
                stats = {row["tool"]: row for row in tp.stats(tp.signature(goal))}
                self.assertGreater(stats["files"]["reward_n"], 0)
                self.assertGreaterEqual(examples.similar(goal)[0]["similarity"], 0)
                result = feedback.followup("That's wrong, try again")
                self.assertIsNotNone(result)
                self.assertEqual(result["kind"], "correction")
                self.assertIsNone(feedback.followup("Thanks"))  # last turn consumed

    def test_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "atlas.db"
            snapshot = Path(tmp) / "learning.json"
            with patch.object(tp, "DB", db), \
                 patch.object(examples, "DB", db), \
                 patch.object(feedback, "DB", db):
                goal = "Check the git status of the project"
                tp.record(tp.signature(goal), "git_status", True, 20)
                examples.save(goal, [{"tool": "git_status"}])
                count = tp.export_json(str(snapshot))
                self.assertGreater(count, 0)
                payload = json.loads(snapshot.read_text())
                self.assertEqual(payload["version"], 1)
                self.assertTrue(payload["tool_policy"])
                counts = tp.import_json(str(snapshot))
                self.assertGreater(counts["tool_policy"], 0)


if __name__ == "__main__":
    unittest.main()
