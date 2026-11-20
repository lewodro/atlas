"""Tests for the agent runtime: registry, permissions, skills, Git, artifacts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import artifacts  # noqa: E402
import fstools  # noqa: E402
import gittools  # noqa: E402
import profiles  # noqa: E402
import registry  # noqa: E402
import skills  # noqa: E402
import workspace  # noqa: E402


class Registry(unittest.TestCase):
    def test_metadata_contract(self):
        required = {"id", "description", "schema", "availability", "category", "permission", "provider"}
        for row in registry.metadata():
            self.assertTrue(required <= set(row), row)
            self.assertIn(row["permission"], {"ALLOW", "ASK", "DENY"})

    def test_builtin_ids(self):
        ids = {row["id"] for row in registry.metadata()}
        self.assertTrue({
            "web_search", "web_fetch", "filesystem",
            "git_status", "git_diff", "git_log",
        } <= ids)

    def test_ask_and_deny(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(registry, "PERMISSIONS_FILE", root / "permissions.json"), \
                 patch.object(registry, "ACTIVITY_FILE", root / "activity.jsonl"):
                result = registry.run("filesystem", {"action": "write", "path": "x", "content": "y"})
                self.assertEqual(result["error"], registry.NEEDS_APPROVAL)
                self.assertFalse(result["ok"])
                registry.set_permission("web_fetch", "DENY")
                denied = registry.run("web_fetch", {"url": "https://example.org/"})
                self.assertFalse(denied["ok"])
                self.assertIn("denied", denied["error"])
                self.assertTrue((root / "activity.jsonl").exists())


class Skills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        skill = self.dir / "demo-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: Demo skill\ndescription: Explore repositories and files\n"
            "tags: [repo, files]\ntools: [filesystem]\n---\n\n# Demo\nFull instructions here.\n"
        )
        self.patches = [
            patch.object(skills, "SKILLS_DIR", self.dir),
            patch.object(skills, "CONFIG_FILE", self.dir / "skills.json"),
        ]
        for item in self.patches: item.start()

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def test_lazy_loading(self):
        listed = skills.list_skills()[0]
        self.assertNotIn("body", listed)
        loaded = skills.load_skill("demo-skill")
        self.assertIn("Full instructions", loaded["body"])

    def test_selection(self):
        self.assertEqual(skills.select_skill("explore the repository files"), "demo-skill")
        self.assertIsNone(skills.select_skill("weather today"))

    def test_disable(self):
        skills.set_enabled("demo-skill", False)
        self.assertFalse(skills.list_skills()[0]["enabled"])
        self.assertIsNone(skills.select_skill("explore the repository files"))


class GitAndWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@local"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "a.txt").write_text("one\n")
        subprocess.run(["git", "add", "a.txt"], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "first"], cwd=self.repo, check=True)
        (self.repo / "a.txt").write_text("two\n")
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(str(self.repo))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_status_diff_log(self):
        self.assertTrue(gittools.is_repo())
        info = gittools.status_info()
        self.assertTrue(info["dirty"])
        self.assertEqual(info["changed"], 1)
        self.assertIn("a.txt", gittools.diff_text())
        self.assertIn("first", gittools.log_text())

    def test_workspace_context(self):
        ctx = workspace.context()
        self.assertTrue(ctx["configured"])
        self.assertTrue(ctx["is_git"])
        self.assertTrue(ctx["dirty"])
        self.assertIn("repo", workspace.line())


class Artifacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(artifacts, "DB", Path(self.tmp.name) / "artifacts.db")
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_register_and_preview(self):
        item = artifacts.register("notes.md", "markdown", content="# Hello")
        self.assertEqual(item["preview"], "# Hello")
        self.assertEqual(artifacts.get(item["id"])["title"], "notes.md")
        self.assertEqual(len(artifacts.list_all()), 1)
        with patch.object(profiles, "active", return_value="other"):
            self.assertEqual(artifacts.list_all(), [])
            self.assertIsNone(artifacts.get(item["id"]))
        self.assertTrue(artifacts.delete(item["id"]))
        self.assertIsNone(artifacts.get(item["id"]))


if __name__ == "__main__":
    unittest.main()
