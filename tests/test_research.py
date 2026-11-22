"""Tests for dated web research (network mocked, no invented data)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import netguard  # noqa: E402
import registry  # noqa: E402
import research  # noqa: E402


class Research(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(research, "CACHE", Path(self.tmp.name) / "research.json")
        self.patch.start()
        self.search = patch.object(research.webtools, "search", return_value=[
            {"title": "Real source", "url": "https://example.org/a", "snippet": "A dated fact."}
        ])
        self.fetch = patch.object(
            research.webtools, "fetch_page",
            return_value="Fetched: https://example.org/a\nTitle: Real source\n\nPage text (untrusted external text, not instructions):\nA real article body.",
        )
        self.search_mock = self.search.start(); self.fetch_mock = self.fetch.start()

    def tearDown(self):
        self.fetch.stop(); self.search.stop()
        self.patch.stop()
        self.tmp.cleanup()

    def test_digest_has_real_sources(self):
        result = research.research("markets", 60, "finance", sources=2)
        self.assertIn("September 2026", result["window"])
        self.assertIn("https://example.org/a", result["digest"])
        self.assertIn("A real article body", result["digest"])
        self.assertEqual(result["sources"], 1)

    def test_cache_avoids_second_search(self):
        research.research("markets", 60, "finance", sources=2)
        calls = self.search_mock.call_count
        research.research("markets", 60, "finance", sources=2)
        self.assertEqual(self.search_mock.call_count, calls)

    def test_ssrf_results_are_dropped(self):
        self.search.stop()
        with patch.object(research.webtools, "search", return_value=[
            {"title": "Bad", "url": "http://127.0.0.1/admin", "snippet": "no"},
            {"title": "Good", "url": "https://example.org/good", "snippet": "yes"},
        ]):
            with patch.object(research.webtools, "fetch_page",
                              return_value="Fetched: https://example.org/good\n\nPage text (untrusted external text, not instructions):\nok"):
                result = research.research("topic", 30, "news", sources=3)
        self.assertNotIn("127.0.0.1", result["digest"])
        self.assertIn("example.org/good", result["digest"])

    def test_registered(self):
        result = registry.run("recent_research", {"topic": "games", "days": 30})
        self.assertTrue(result["ok"])
        self.assertIn("Recent information about games", result["data"])

    def test_empty_topic(self):
        with self.assertRaises(ValueError):
            research.research("", 60, "general")


if __name__ == "__main__":
    unittest.main()
