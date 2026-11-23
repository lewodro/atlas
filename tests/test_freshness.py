"""Freshness enforcement, grounded research and memory-regression tests.

All tests here are offline and deterministic; optional live checks live in
eval/run_web_eval.py (--live) and use the configured local model.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import freshness  # noqa: E402
import librarian  # noqa: E402
import main  # noqa: E402
import orchestrator  # noqa: E402
import registry  # noqa: E402
import skills  # noqa: E402
import toolcalls  # noqa: E402


class Msg:
    def __init__(self, content: str = "", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


def _result(tool: str, data: str, ok: bool = True) -> dict:
    return {"tool": tool, "ok": ok, "data": data, "error": None, "duration_ms": 1}


SEARCH_TEXT = (
    "Web results for 'model releases November 2026':\n"
    "1. Live tracker\n   https://example.org/november-2026\n"
    "   GPT-6 released November 2026.\n"
)
FETCH_TEXT = (
    "Fetched: https://example.org/november-2026\nTitle: Live tracker\n\n"
    "GPT-6 launched in November 2026. Gemini 4 Neon launched November 18, 2026."
)


class Classifier(unittest.TestCase):
    def test_required_cases(self):
        cases = {
            "A": "What are the latest AI model releases in November 2026?",
            "B": "Who is the current CEO of OpenAI?",
            "E": "latest news",
            "F": "Research the latest AI tools and security breaches from November 2026.",
            "user": "Be more specific, use 2026 November news.",
            "today": "What happened today in AI?",
            "month": "new releases this month",
        }
        for name, text in cases.items():
            with self.subTest(case=name):
                self.assertTrue(freshness.required(text), text)

    def test_not_required_cases(self):
        for text in (
            "What is Python list comprehension?",
            "Tell me about the Roman Empire.",
            "I am learning Rust and prefer short answers.",
            "New York is a large city.",
        ):
            with self.subTest(text=text):
                self.assertFalse(freshness.required(text), text)

    def test_period_and_queries(self):
        self.assertEqual(
            freshness.period("AI releases November 2026"), "November 2026"
        )
        self.assertEqual(
            freshness.period("AI releases 2026 November"), "November 2026"
        )
        queries = freshness.suggest_queries(
            "Research the latest AI tools and security breaches from November 2026."
        )
        self.assertEqual(len(queries), 2)
        self.assertIn("ai tools November 2026", queries)
        self.assertIn("security breaches November 2026", queries)

    def test_skill_and_role_are_forced(self):
        text = "What are the latest AI model releases in November 2026?"
        self.assertEqual(skills.select_skill(text), "web-research")
        self.assertEqual(orchestrator.select_role(text), "research")


class Repair(unittest.TestCase):
    def test_valid_json_in_prose(self):
        calls, clean = toolcalls.extract(
            'First <tool_call>{"name":"web_search","arguments":{"query":"x"}}</tool_call> then answer'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "web_search")
        self.assertEqual(calls[0]["arguments"], {"query": "x"})
        self.assertNotIn("<tool_call>", clean)

    def test_slightly_malformed_json(self):
        calls, _ = toolcalls.extract(
            '{"name": "web_fetch", "arguments": {"url": "https://example.org"},}'
        )
        self.assertEqual(calls, [
            {"name": "web_fetch", "arguments": {"url": "https://example.org"}}
        ])

    def test_unterminated_call(self):
        calls, clean = toolcalls.extract(
            '<tool_call>{"name":"web_search","arguments":{"query":"q"}'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["arguments"], {"query": "q"})
        self.assertNotIn("<tool_call>", clean)

    def test_no_call_is_not_invented(self):
        calls, clean = toolcalls.extract("I should probably search for that.")
        self.assertEqual(calls, [])
        self.assertIn("search", clean)


class TrackerState(unittest.TestCase):
    def test_blocks_until_search_succeeds(self):
        tracker = freshness.Tracker(True, "November 2026")
        self.assertTrue(tracker.blocked())
        tracker.note_call("web_search")
        tracker.note_result("web_search", True, SEARCH_TEXT)
        self.assertFalse(tracker.blocked())
        self.assertTrue(tracker.can_auto_fetch())

    def test_failed_results_do_not_count(self):
        tracker = freshness.Tracker(True)
        tracker.note_result("web_search", True, "No usable results for 'x'.")
        self.assertTrue(tracker.blocked())
        self.assertEqual(freshness.first_url(SEARCH_TEXT), "https://example.org/november-2026")

    def test_corrections_are_bounded(self):
        tracker = freshness.Tracker(True, "November 2026")
        self.assertEqual(tracker.correct(), freshness.CORRECTION)
        self.assertEqual(tracker.correct(), freshness.CORRECTION)
        self.assertIsNone(tracker.correct())
        self.assertIn("couldn't verify current November 2026", freshness.failure("November 2026"))

    def test_auto_tools_are_bounded(self):
        tracker = freshness.Tracker(True)
        self.assertTrue(tracker.can_auto_search())
        tracker.auto_searches = 2
        self.assertFalse(tracker.can_auto_search())


class MemoryRegression(unittest.TestCase):
    def test_research_topic_is_not_memory(self):
        payload = json.dumps({
            "facts": ["The user is interested in latest AI news November 2026."]
        })
        with patch.object(librarian, "chat", return_value=Msg(payload)) as chat:
            self.assertEqual(librarian.extract("latest AI news November 2026"), [])
            chat.assert_not_called()

    def test_stable_fact_still_goes_through_model(self):
        with patch.object(librarian, "chat", return_value=Msg('{"facts":[]}')) as chat:
            librarian.extract("I am learning Rust.")
            chat.assert_called_once()


class HarnessIntegration(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(main, "build_system", return_value="system"),
            patch.object(main.memory, "log_turn"),
            patch.object(main.memory, "cli_session", return_value="cli"),
            patch.object(main, "journal"),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    def test_fresh_query_searches_and_fetches_even_if_model_never_calls(self):
        replies = [
            Msg("I should look that up."),
            Msg("I need to check the sources."),
            Msg("GPT-6 launched in November 2026 (https://example.org/november-2026)."),
        ]
        used = []

        def run(tool, args, **kwargs):
            used.append((tool, args))
            if tool == "web_search":
                return _result(tool, SEARCH_TEXT)
            return _result(tool, FETCH_TEXT)

        with patch.object(main, "chat", side_effect=replies), \
             patch.object(registry, "run", side_effect=run):
            answer = main.turn(
                [{"role": "system", "content": ""}],
                "What are the latest AI model releases in November 2026?",
                "general", write_memory=False,
            )
        self.assertEqual([name for name, _ in used], ["web_search", "web_fetch"])
        self.assertIn("GPT-6", answer)
        self.assertNotIn("Stable Diffusion", answer)

    def test_non_fresh_query_does_not_search(self):
        with patch.object(main, "chat", return_value=Msg("A list comprehension builds a list.")), \
             patch.object(registry, "run") as run:
            answer = main.turn(
                [{"role": "system", "content": ""}],
                "What is Python list comprehension?", "general", write_memory=False,
            )
        run.assert_not_called()
        self.assertIn("comprehension", answer)

    def test_search_failure_is_honest_and_bounded(self):
        replies = [Msg("I cannot answer.") for _ in range(4)]
        used = []

        def run(tool, args, **kwargs):
            used.append(tool)
            return _result(tool, "No usable results for 'x'.")

        with patch.object(main, "chat", side_effect=replies), \
             patch.object(registry, "run", side_effect=run):
            answer = main.turn(
                [{"role": "system", "content": ""}],
                "What are the latest AI model releases in November 2026?",
                "general", write_memory=False,
            )
        self.assertEqual(
            answer,
            "I couldn't verify current November 2026 information from the web.",
        )
        self.assertEqual(used, ["web_search", "web_search"])


if __name__ == "__main__":
    unittest.main()
