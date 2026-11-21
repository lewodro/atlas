"""Tests for the file manager and the allowlisted terminal tool."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fstools  # noqa: E402
import registry  # noqa: E402
import termtools  # noqa: E402


class Terminal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@local"], cwd=self.repo, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo, check=True)
        (self.repo / "README.md").write_text("demo\n")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(["git", "commit", "-qm", "first"], cwd=self.repo, check=True)
        (self.repo / "extra.txt").write_text("new\n")
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(str(self.repo))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_real_commands(self):
        self.assertIn("README.md", termtools.run("ls"))
        self.assertIn("extra.txt", termtools.run("git status"))
        self.assertIn("first", termtools.run("git log"))
        self.assertIn("repo", termtools.run("pwd"))
        self.assertIn("first", termtools.run("git_log"))
        self.assertIn("extra.txt", termtools.run("git_status"))
        self.assertIn("README.md", termtools.run("tree"))

    def test_dangerous_commands_are_refused(self):
        for command in [
            "rm -rf /", "ls; rm -rf /", "ls | cat", "git push --force",
            "git reset --hard", "cat /etc/passwd", "python -c 'print(1)'",
            "ls > out.txt", "ls $(whoami)",
        ]:
            with self.subTest(command=command), self.assertRaises(fstools.ToolError):
                termtools.run(command)


class FileManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "workspace"
        root.mkdir()
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(str(root))
        self.root = root

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_mkdir_move_delete(self):
        self.assertIn("Created directory", fstools.mkdir("demo"))
        self.assertIn("Wrote", fstools.write("notes.txt", "hello"))
        self.assertIn("Moved", fstools.move("notes.txt", "demo/notes.txt"))
        self.assertIn("hello", fstools.read("demo/notes.txt"))
        self.assertIn("Deleted", fstools.delete("demo/notes.txt"))
        self.assertIn("Deleted", fstools.delete("demo"))

    def test_delete_root_and_hidden_refused(self):
        with self.assertRaises(fstools.ToolError):
            fstools.delete(".")
        (self.root / ".hidden").write_text("secret")
        with self.assertRaises(fstools.ToolError):
            fstools.delete(".hidden")


class GitInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "fresh"
        root.mkdir()
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(str(root))
        self.root = root

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_init_creates_repo_once(self):
        import gittools
        self.assertFalse(gittools.is_repo())
        self.assertIn("Initialized", gittools.init_repo())
        self.assertTrue(gittools.is_repo())
        self.assertIn("already", gittools.init_repo())


class RegistryTools(unittest.TestCase):
    def test_new_tools_registered(self):
        ids = {row["id"] for row in registry.metadata()}
        self.assertIn("files", ids)
        self.assertIn("terminal", ids)
        terminal = next(r for r in registry.metadata() if r["id"] == "terminal")
        self.assertEqual(terminal["permission"], "ALLOW")
        manager = next(r for r in registry.metadata() if r["id"] == "files")
        self.assertEqual(manager["permission"], "ASK")


if __name__ == "__main__":
    unittest.main()
