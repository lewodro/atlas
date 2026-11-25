"""Provider presets, egress ledger and user-defined tools."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import customtools  # noqa: E402
import egress  # noqa: E402
import providers  # noqa: E402


class Providers(unittest.TestCase):
    def test_presets(self):
        self.assertTrue(providers.is_local("http://127.0.0.1:11434/v1"))
        self.assertFalse(providers.is_local("https://openrouter.ai/api/v1"))
        openrouter = providers.get("openrouter")
        self.assertEqual(openrouter["key_env"], "OPENROUTER_API_KEY")
        self.assertIn("prompts", openrouter["egress"])
        ids = [row["id"] for row in providers.list_presets()]
        self.assertEqual(ids[:4], ["ollama", "lmstudio", "llamacpp", "vllm"])
        self.assertIn("openrouter", ids)

    def test_remote_guard_and_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            with patch.object(egress, "SETTINGS", settings), \
                 patch.dict("os.environ", {}, clear=False):
                egress.guard("http://127.0.0.1:11434/v1")
                with patch.dict("os.environ", {"ATLAS_ALLOW_REMOTE": ""}):
                    with self.assertRaises(RuntimeError):
                        egress.guard("https://api.openai.com/v1")
                egress.approve_remote()
                egress.guard("https://api.openai.com/v1")
                self.assertTrue(json.loads(settings.read_text())["remote_ok"])


class Ledger(unittest.TestCase):
    def test_preview_flags_and_redaction(self):
        messages = [
            {"role": "system", "content": "You are Atlas"},
            {"role": "user", "content": "read /Users/me/notes.md http://example.org a@b.com"},
        ]
        tools = [{"type": "function", "function": {"name": "files"}}]
        summary = egress.preview(messages, tools, "https://openrouter.ai/api/v1", "m")
        self.assertEqual(summary["provider"], "openrouter")
        self.assertFalse(summary["local"])
        self.assertEqual(summary["messages"], {"system": 1, "user": 1})
        self.assertEqual(summary["tools"], ["files"])
        self.assertTrue(summary["flags"]["local_paths"])
        self.assertTrue(summary["flags"]["urls"])
        self.assertTrue(summary["flags"]["emails"])
        self.assertNotIn("notes.md", json.dumps(summary))

    def test_record_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(egress, "LEDGER", Path(tmp) / "egress.jsonl"):
                egress.record(
                    [{"role": "user", "content": "hello"}], None,
                    "http://127.0.0.1:11434/v1", "qwen2.5:3b",
                )
                rows = egress.ledger()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["model"], "qwen2.5:3b")
                self.assertTrue(rows[0]["local"])


class CustomTools(unittest.TestCase):
    def test_validate(self):
        self.assertEqual(customtools.validate(customtools.example()), "")
        self.assertTrue(customtools.validate({
            "name": "bad", "kind": "command", "command": "rm -rf /"
        }))
        self.assertTrue(customtools.validate({
            "name": "bad", "kind": "http", "url": "http://127.0.0.1:22/admin"
        }))

    def test_echo_handler(self):
        handler = customtools._handler(customtools.example())
        result = json.loads(handler({"text": "hi"}))
        self.assertEqual(result["args"]["text"], "hi")


if __name__ == "__main__":
    unittest.main()
