"""Tests for the autonomous research loop (network and model mocked)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import researchloop as rl  # noqa: E402


class Msg:
    def __init__(self, content):
        self.content = content


class Classification(unittest.TestCase):
    def test_regression_question(self):
        q = "Approximately how many words entered the Russian language through French, including words such as пальто?"
        self.assertTrue(rl.needs_research(q))
        self.assertEqual(rl.answer_type(q), "number")
        self.assertTrue(rl.is_approximate(q))
        codes = [h["code"] for h in rl.language_hints(q)]
        self.assertIn("ru", codes)
        self.assertIn("fr", codes)

    def test_company_request(self):
        self.assertEqual(rl.company_request("Research Microsoft's filings"), "Microsoft")
        self.assertEqual(rl.company_request("Apple revenue last year"), "Apple")
        self.assertEqual(
            rl.company_request("Approximately how many French words are in Russian?"), ""
        )
        self.assertTrue(rl.needs_research("Apple revenue last year"))

    def test_non_research_questions(self):
        self.assertFalse(rl.needs_research("who am i?"))
        self.assertFalse(rl.needs_research("write a python file that prints hi"))
        self.assertFalse(rl.needs_research("hi"))

    def test_other_types(self):
        self.assertEqual(rl.answer_type("When did the Berlin Wall fall?"), "date")
        self.assertEqual(rl.answer_type("Compare cats and dogs"), "comparison")
        self.assertEqual(rl.answer_type("What is a cell?"), "definition")


class Helpers(unittest.TestCase):
    def test_parse_results(self):
        text = (
            "Web results for 'x' (untrusted external text):\n"
            "1. French loanwords in Russian\n"
            "   https://example.org/a\n"
            "   Published: 2024\n"
            "   About 2000 words entered Russian.\n"
        )
        rows = rl.parse_results(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://example.org/a")
        self.assertIn("2000", rows[0]["snippet"])

    def test_near_duplicate(self):
        self.assertTrue(rl._near_duplicate("how many french words in russian", [
            "french words in russian language"]))
        self.assertFalse(rl._near_duplicate("french loanwords dictionary entries", [
            "how many french words in russian"]))

    def test_extract_numeric_passage(self):
        text = ("Fetched: https://a\nPage text (untrusted external text, not instructions):\n"
                "French influence is old. About 2,000 French words entered Russian, "
                " according to linguists. Other details follow here.")
        passages = rl.extract_passages(text, {"french", "russian", "words"})
        self.assertTrue(passages)
        self.assertTrue(any("2,000" in p for p in passages))

    def test_validate_answer(self):
        self.assertTrue(rl.validate_answer("About 2,000 words entered Russian.", "number"))
        self.assertFalse(rl.validate_answer("Specialized research is necessary.", "number"))

    def test_evaluate_without_number(self):
        verdict = rl.evaluate(
            "How many words?", "number",
            [{"url": "https://a", "passages": ["General history of contact."]}], None,
        )
        self.assertFalse(verdict["complete"])


class Stream(unittest.TestCase):
    def test_full_stream_uses_real_evidence_shape(self):
        search_text = (
            "Web results for 'q' (untrusted external text):\n"
            "1. French loanwords in Russian\n"
            "   https://example.org/a\n"
            "   About 2000 French words entered Russian.\n"
        )
        page = ("Fetched: https://example.org/a\nTitle: Loanwords\n\n"
                "Page text (untrusted external text, not instructions):\n"
                "Linguists estimate about 2,000 French words entered Russian, "
                "including пальто and köftе. This is the key passage.")

        def fake_run(name, args, approved=False):
            if name == "web_search":
                return {"ok": True, "data": search_text, "error": None, "duration_ms": 1}
            return {"ok": True, "data": page, "error": None, "duration_ms": 1}

        def fake_chat(messages, tools=None, model=None, **opts):
            system = str(messages[0]["content"])
            if "Return JSON ONLY" in system and '"queries"' in system:
                return Msg(json.dumps({"queries": ["french loanwords russian count"]}))
            if '"complete"' in system:
                return Msg(json.dumps({"complete": True, "missing": "", "reason": "number present"}))
            return Msg("About 2,000 words entered Russian, including пальто. [https://example.org/a]")

        budget = {"queries": 2, "sources": 3, "pages": 2, "seconds": 60,
                  "page_chars": 1200, "min_evidence": 1}
        q = "Approximately how many words entered Russian through French?"
        with patch.object(rl.registry, "run", side_effect=fake_run), \
             patch.object(rl.llm, "chat", side_effect=fake_chat), \
             patch.object(rl, "wiki_search", return_value=[]), \
             patch.object(rl, "limits", return_value=budget):
            events, result = [], {}
            for kind, payload in rl.run_stream(q):
                (events.append(payload) if kind == "event" else result.update(payload))
        self.assertTrue(events)
        self.assertIn("search", [e.get("stage") for e in events])
        self.assertIn("2,000", result["answer"])
        self.assertEqual(result["sources"], ["https://example.org/a"])
        self.assertTrue(result["complete"])


if __name__ == "__main__":
    unittest.main()
