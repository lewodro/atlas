"""Fast, offline regression tests. No Ollama, no network.

    uv run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402
import models  # noqa: E402
import profiles  # noqa: E402


class Retrieval(unittest.TestCase):
    def test_stem_matches_word_forms(self):
        self.assertIn("programm", memory.keywords("programming programmer programs"))
        self.assertIn("write", memory.keywords("writes writing"))

    def test_keyword_prefix_fallback(self):
        """'mac' must find a note that says 'macbook' when embeddings are off."""
        with tempfile.TemporaryDirectory() as folder:
            note = Path(folder) / "note.md"
            note.write_text("---\ntype: atlas-memory\n---\nThe user owns an 8 gb m1 macbook.")
            with patch.object(memory, "note_paths", return_value=[note]):
                hits = memory._keyword_hits("how much RAM does my mac have")
        self.assertTrue(hits)

    def test_keyword_never_hides_semantic(self):
        """The 2026-11 bug: one weak keyword hit suppressed semantic recall."""
        with tempfile.TemporaryDirectory() as folder:
            weak = Path(folder) / "weak.md"
            strong = Path(folder) / "strong.md"
            weak.touch()
            strong.touch()
            ranked = memory.rank_hits(
                [(0.9, weak)],
                [(0.8, strong)],  # weighted x2 -> wins
            )
        self.assertEqual(ranked[0][0], strong)


class Settings(unittest.TestCase):
    def test_load_overrides_defaults_and_survives_bad_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"model": "other:7b"}')
            with patch.object(models, "SETTINGS", path):
                self.assertEqual(models.load()["model"], "other:7b")
                path.write_text("{broken")
                self.assertEqual(models.load()["model"], models.DEFAULTS["model"])
                models.save(model="back:3b")
                self.assertEqual(json.loads(path.read_text())["model"], "back:3b")


if __name__ == "__main__":
    unittest.main()


class Discovery(unittest.TestCase):
    def test_known_local_runtimes_are_probed(self):
        names = {r["name"] for r in models.scan_runtimes(timeout=0.3)}
        self.assertTrue({"Ollama", "LM Studio", "llama.cpp", "vLLM"} <= names)

    def test_clean_install_autopicks_first_reachable_runtime(self):
        fake = [
            {"name": "Ollama", "base_url": "http://127.0.0.1:11434/v1", "models": ["q:3b"]},
            {"name": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "models": []},
        ]
        with (
            patch.object(models, "SETTINGS", Path("/nonexistent/settings.json")),
            patch.dict(os.environ, {"ATLAS_MODEL": "", "ATLAS_BASE_URL": ""}),
            patch.object(models, "_AUTO", None),
            patch.object(models, "scan_runtimes", return_value=fake),
        ):
            picked = models.load()
        self.assertEqual(picked["model"], "q:3b")
        self.assertEqual(picked["base_url"], "http://127.0.0.1:11434/v1")


class ProfileMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [
            patch.object(profiles, "DB", root / "atlas.db"),
            patch.object(profiles, "ACTIVE_FILE", root / "profile.json"),
        ]
        for item in self.patches:
            item.start()
        profiles.migrate()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_profiles_are_isolated(self):
        alice = profiles.create("Alice")
        bob = profiles.create("Bob")
        profiles.add(alice, "identity", "Alice lives in Vancouver.")
        profiles.add(bob, "identity", "Bob lives in Toronto.")
        self.assertTrue(any("Vancouver" in r["content"] for r in profiles.search(alice, "Vancouver")))
        self.assertFalse(any("Vancouver" in r["content"] for r in profiles.search(bob, "Vancouver")))
        profiles.switch(bob)
        self.assertEqual(profiles.active(), bob)
        self.assertTrue(all(r["user_id"] == bob for r in profiles.list_all(bob)))

    def test_secrets_are_rejected(self):
        with self.assertRaises(ValueError):
            profiles.add("default", "temporary", "my api key is sk-abcdef123456")

    def test_correction_and_forget(self):
        memory_id, status = profiles.add(
            "default", "temporary", "Temporary codename is Blue Lantern 47."
        )
        self.assertEqual(status, "saved")
        profiles.update(memory_id, "default", "Temporary codename is Blue Lantern 48.")
        self.assertIn("48", profiles.get(memory_id, "default")["content"])
        self.assertTrue(profiles.forget(memory_id, "default"))
        self.assertIsNone(profiles.get(memory_id, "default"))


class OfflineMemory(unittest.TestCase):
    def test_retrieval_works_with_no_network_sockets(self):
        def blocked(*args, **kwargs):
            raise AssertionError("external network call during memory retrieval")

        with patch("socket.socket.connect", side_effect=blocked):
            context = memory.recall("where did I live before Edmonton")
        self.assertTrue(context)


class VaultIsolation(unittest.TestCase):
    def test_markdown_vault_is_scoped_to_profile(self):
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        with (
            patch.object(profiles, "DB", root / "atlas.db"),
            patch.object(profiles, "ACTIVE_FILE", root / "profile.json"),
            patch.object(memory, "NOTES", root / "notes"),
            patch.object(memory, "EMBED_CACHE", root / "embeddings.json"),
        ):
            profiles.migrate()
            (root / "notes").mkdir()
            (root / "notes" / "default-fact.md").write_text(
                "---\ntype: atlas-memory\n---\nThe user is Alice."
            )
            self.assertEqual(len(memory.note_paths()), 1)
            other = profiles.create("Other")
            profiles.switch(other)
            self.assertEqual(memory.note_paths(), [])
            self.assertNotIn("Alice", memory.recall("who am i"))
        tmp.cleanup()
