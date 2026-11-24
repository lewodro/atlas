"""Tests for the composer's slash token helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node not installed")
class SlashHelpers(unittest.TestCase):
    def node(self, expression):
        script = (
            "const s=require(process.argv[1]);"
            "process.stdout.write(JSON.stringify(eval(process.argv[2])));"
        )
        result = subprocess.run(
            ["node", "-e", script, str(ROOT / "web" / "slash.js"), expression],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    def test_slash_inside_sentence(self):
        found = self.node("s.findSlashToken('study this /res world', 15)")
        self.assertEqual(found, {"start": 11, "end": 15, "query": "res"})

    def test_slash_at_start(self):
        found = self.node("s.findSlashToken('/goal build a game', 5)")
        self.assertEqual(found, {"start": 0, "end": 5, "query": "goal"})

    def test_no_token_in_plain_text(self):
        self.assertIsNone(self.node("s.findSlashToken('hello world', 11)"))
        self.assertIsNone(self.node("s.findSlashToken('mail a/b', 7)"))

    def test_replace_keeps_surrounding_text(self):
        token = {"start": 6, "end": 10, "query": "res"}
        value = self.node("s.replaceSlashToken('hello /res world', "
                          + json.dumps(token) + ", '/research ')")
        self.assertEqual(value, "hello /research  world")


if __name__ == "__main__":
    unittest.main()
