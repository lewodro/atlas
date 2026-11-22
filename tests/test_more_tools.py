"""Tests for the remaining tool surfaces (network/process mocked where needed)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import codetools  # noqa: E402
import fstools  # noqa: E402
import githubtools  # noqa: E402
import imagetools  # noqa: E402
import providers  # noqa: E402
import registry  # noqa: E402


class GitHub(unittest.TestCase):
    def test_repo_validation(self):
        with patch.object(githubtools, "FILE", Path(tempfile.gettempdir()) / "none-gh.json"):
            with self.assertRaises(fstools.ToolError):
                githubtools._repo("../../etc/passwd")
            with self.assertRaises(fstools.ToolError):
                githubtools._repo("evil/repo")

    def test_issues_are_read_only(self):
        payload = [{"number": 8, "title": "PR", "state": "open", "html_url": "u",
                    "pull_request": {}},
                   {"number": 7, "title": "Issue", "state": "open", "html_url": "u"}]
        with patch.object(githubtools, "_api", return_value=payload) as api:
            text = githubtools.issues({"repo": "lewodro/atlas", "limit": 2})
        self.assertIn("#7", text)
        self.assertNotIn("#8", text)
        self.assertEqual(api.call_args.args[0], "repos/lewodro/atlas/issues")


class ImageTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(fstools, "CONFIG_FILE", Path(self.tmp.name) / "tools.json")
        self.patch.start()
        fstools.configure_workspace(self.tmp.name)

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_generate_and_edit(self):
        made = imagetools.generate({"prompt": "teal hills", "path": "art.svg", "title": "Hills"})
        self.assertTrue(made["ok"])
        self.assertEqual(made["artifact_hint"]["kind"], "image")
        updated = imagetools.edit({"path": "art.svg", "caption": "edited"})
        self.assertTrue(updated["ok"])
        text = Path(self.tmp.name, "art.svg").read_text()
        self.assertIn("edited", text)
        self.assertIn("<svg", text)


class CodeExecution(unittest.TestCase):
    def test_runs_simple_python(self):
        out = codetools.execute('print("hello from sandbox")')
        self.assertIn("hello from sandbox", out)
        self.assertIn("exit: 0", out)

    def test_blocks_network_import(self):
        out = codetools.execute("import socket")
        self.assertIn("blocked import: socket", out)


class Providers(unittest.TestCase):
    def test_register_validation_and_list(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "providers.json"
            with patch.object(providers, "FILE", path), \
                 patch.object(providers.netguard, "vetted_target", return_value=None):
                row = providers.register("local", "Local", "http://127.0.0.1:9999", [
                    {"id": "ping", "description": "Ping", "parameters": {"type": "object"}},
                ])
                self.assertEqual(row["id"], "local")
                self.assertEqual(len(providers.list_providers()), 1)
                self.assertTrue(providers.remove("local"))

    def test_invoke_result(self):
        provider = {"id": "local", "name": "Local", "base_url": "http://127.0.0.1:9999"}
        with patch.object(providers.netguard, "vetted_target", return_value=None), \
             patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"result":"pong"}')):
            self.assertEqual(providers.invoke(provider, "ping", {}), "pong")


class Registry(unittest.TestCase):
    def test_all_new_tools_registered(self):
        ids = {row["id"] for row in registry.metadata()}
        expected = {"terminal", "github_issues", "github_prs", "github_repo",
                    "image_generate", "image_edit", "code_execute"}
        self.assertTrue(expected <= ids)


if __name__ == "__main__":
    unittest.main()
