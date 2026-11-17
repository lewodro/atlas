from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import memory


class MemoryFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.notes = root / "vault" / "Atlas" / "Memory"
        self.data = root / "data"
        self.notes.mkdir(parents=True)
        self.data.mkdir(parents=True)
        self.globals = patch.multiple(
            memory,
            NOTES=self.notes,
            DB_PATH=self.data / "atlas.db",
            EMBED_CACHE=self.data / "embeddings.json",
        )
        self.globals.start()

    def tearDown(self) -> None:
        self.globals.stop()
        self.tmp.cleanup()

    def test_remember_writes_obsidian_properties(self) -> None:
        path = memory.remember("The user is learning Rust.", ["learning", "rust"])
        text = path.read_text(encoding="utf-8")

        self.assertEqual(path.parent, self.notes)
        self.assertIn("type: atlas-memory", text)
        self.assertIn("tags: [learning, rust]", text)
        self.assertIn("updated:", text)
        self.assertTrue(text.endswith("The user is learning Rust.\n"))

    def test_keyword_recall_does_not_call_embeddings(self) -> None:
        memory.remember("The user is learning Rust.", ["learning"])
        with patch.dict(os.environ, {"ATLAS_RETRIEVAL": "hybrid"}), patch.object(
            memory, "_semantic_hits", side_effect=AssertionError("semantic call")
        ):
            result = memory.recall("Help with Rust ownership")

        self.assertIn("learning Rust", result)

    def test_manual_memory_is_deduplicated(self) -> None:
        first = memory.remember("The user is learning Rust.", ["manual"])
        second = memory.remember("The user is learning Rust.", ["manual"])
        self.assertEqual(first, second)
        self.assertEqual(len(memory.note_paths()), 1)

    def test_update_requires_exact_note_and_preserves_created_time(self) -> None:
        path = memory.remember("The user uses Fedora 40.", ["setup"])
        before = path.read_text(encoding="utf-8")
        created = next(
            line for line in before.splitlines() if line.startswith("created:")
        )

        updated = memory.update_note(path.stem, "The user uses Fedora 41.")
        after = updated.read_text(encoding="utf-8")

        self.assertEqual(path, updated)
        self.assertIn(created, after)
        self.assertIn("The user uses Fedora 41.", after)
        self.assertNotIn("Fedora 40", after)
        with self.assertRaises(ValueError):
            memory.update_note("not-a-real-note", "The user uses Debian.")


if __name__ == "__main__":
    unittest.main()
