"""Offline tests for fresh-clone config, model switching and memory portability."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import check  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402
import models  # noqa: E402
import profiles  # noqa: E402


class ProviderRegistry(unittest.TestCase):
    def test_url_helpers(self):
        self.assertEqual(config._openai_url("http://127.0.0.1:11434"),
                         "http://127.0.0.1:11434/v1")
        self.assertEqual(config._root("http://127.0.0.1:11434/v1"),
                         "http://127.0.0.1:11434")

    def test_registry_has_healthy_defaults(self):
        self.assertTrue({"ollama", "lmstudio", "llamacpp", "vllm"} <= set(config.PROVIDERS))
        for key, preset in config.PROVIDERS.items():
            self.assertTrue(preset["api_key"], f"{key} needs a non-empty local key")
            self.assertTrue(preset["base_url"].endswith("/v1"), key)
            self.assertTrue(preset["install"], key)

    def test_provider_lookup(self):
        self.assertEqual(config.provider_for_base_url("http://127.0.0.1:11434/v1"), "ollama")
        self.assertEqual(config.provider_for_base_url("http://127.0.0.1:1234/v1"), "lmstudio")
        self.assertEqual(config.provider_for_base_url("https://api.example.com/v1"), "")

    def test_gui_and_cli_share_registry(self):
        self.assertEqual(
            models.RUNTIMES,
            [(p["name"], p["base_url"]) for p in config.PROVIDERS.values()],
        )


class BoundedGeneration(unittest.TestCase):
    def test_empty_length_response_retries_once_with_larger_cap(self):
        first = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=None),
                finish_reason="length",
            )]
        )
        second = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="ready", tool_calls=None),
                finish_reason="stop",
            )]
        )
        client = MagicMock()
        client.chat.completions.create.side_effect = [first, second]
        with patch.object(llm, "active", return_value=(client, "model-x")):
            reply = llm.chat([{"role": "user", "content": "hi"}], temperature=0.2)
        self.assertEqual(reply.content, "ready")
        calls = client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0].kwargs["max_tokens"], config.MAX_TOKENS)
        self.assertEqual(calls[1].kwargs["max_tokens"], min(config.MAX_TOKENS * 2, 2048))
        self.assertEqual(calls[1].kwargs["temperature"], 0.2)


class Credentials(unittest.TestCase):
    def test_empty_api_key_is_replaced(self):
        with patch.object(llm, "OpenAI") as client:
            llm._clients.clear()
            llm._client("http://127.0.0.1:19999/v1", "")
            self.assertEqual(client.call_args.kwargs["api_key"], config.API_KEY)
            self.assertTrue(client.call_args.kwargs["api_key"])


class Doctor(unittest.TestCase):
    def test_errors_are_redacted(self):
        text = check._safe_error(RuntimeError("bad sk-abcdefghijklmnop for host"))
        self.assertNotIn("sk-abcdefghijklmnop", text)
        self.assertIn("***", text)

    def test_all_documented_checks_exist(self):
        for name in ("python_version", "deps", "env_file", "configuration",
                     "provider_registry", "memory_store", "required_ports",
                     "ollama_status", "lmstudio_status",
                     "selected_model_installed", "model_reachable",
                     "workspace_config", "notes_dir"):
            self.assertTrue(callable(getattr(check, name)), name)


class MemoryPortability(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_patch = patch.object(profiles, "DB", self.root / "atlas.db")
        self.active_patch = patch.object(
            profiles, "ACTIVE_FILE", self.root / "profile.json"
        )
        self.db_patch.start()
        self.active_patch.start()
        profiles.migrate()

    def tearDown(self):
        self.active_patch.stop()
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_export_import_roundtrip_preserves_ids(self):
        first, _ = profiles.add("default", "identity", "The user is learning Rust.")
        second, _ = profiles.add("default", "projects", "Building a small game.")
        payload = profiles.export("default")
        self.assertEqual(payload["format"], "atlas-memory")
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["memories"]), 2)

        target = "u-imported"
        # Simulate a different machine: a fresh database with no id collisions.
        with patch.object(profiles, "DB", self.root / "other-machine.db"):
            profiles.migrate()
            result = profiles.import_data(payload, user=target)
            self.assertEqual(result["imported"], 2)
            rows = profiles.list_all(target)
        self.assertEqual({r["id"] for r in rows}, {first, second})
        self.assertEqual({r["category"] for r in rows}, {"identity", "projects"})

    def test_reimport_is_deduplicated(self):
        profiles.add("default", "identity", "The user prefers short answers.")
        payload = profiles.export("default")
        profiles.import_data(payload, user="u-again")
        again = profiles.import_data(payload, user="u-again")
        self.assertEqual(again["duplicates"], 1)
        self.assertEqual(again["imported"], 0)
        self.assertEqual(len(profiles.list_all("u-again")), 1)

    def test_import_validates_and_refuses_secrets(self):
        with self.assertRaisesRegex(ValueError, "unsupported memory format"):
            profiles.import_data({"format": "other", "memories": []})
        with self.assertRaisesRegex(ValueError, "newer than"):
            profiles.import_data({"format": "atlas-memory", "version": 999, "memories": []})
        with self.assertRaisesRegex(ValueError, "memories"):
            profiles.import_data({"format": "atlas-memory", "version": 1})

        result = profiles.import_data({
            "format": "atlas-memory", "version": 1,
            "profile": {"id": "default"},
            "memories": [
                {"id": 7, "category": "identity", "content": "sk-abcdefghijklmnop is my key"},
                {"id": 8, "category": "identity", "content": "The user likes tea."},
            ],
        })
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["imported"], 1)

    def test_legacy_export_shape_imports(self):
        result = profiles.import_data({
            "profile": "default",
            "memories": [{"id": 3, "category": "identity", "content": "The user runs Linux."}],
        })
        self.assertEqual(result["imported"], 1)
        self.assertEqual(profiles.list_all("default")[0]["content"], "The user runs Linux.")


if __name__ == "__main__":
    unittest.main()
