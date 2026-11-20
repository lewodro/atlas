"""Offline tests for the three real tools. No network, no model calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fstools  # noqa: E402
import main  # noqa: E402
import netguard  # noqa: E402
import webtools  # noqa: E402


class NetworkGuard(unittest.TestCase):
    def test_private_targets_are_refused(self):
        for url in [
            "http://127.0.0.1:443/x",
            "https://10.0.0.5/",
            "https://169.254.169.254/latest/meta-data/",
            "http://[::1]/",
            "file:///etc/passwd",
            "https://user:pass@example.com/",
            "https://example.com:8080/",
        ]:
            with self.subTest(url=url), self.assertRaises(netguard.NetError):
                netguard.vetted_target(url)

    def test_public_target_is_pinned(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]):
            scheme, host, port, path, ips = netguard.vetted_target("https://example.com/a?q=1")
        self.assertEqual((scheme, host, port, ips),
                         ("https", "example.com", 443, ["93.184.216.34"]))
        self.assertEqual(path, "/a?q=1")

    def test_dns_rebinding_answer_is_refused(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]), self.assertRaises(netguard.NetError):
            netguard.vetted_target("https://example.com/")

    def test_body_cap(self):
        class Response:
            status = 200
            def getheader(self, name):
                return "text/plain" if name == "Content-Type" else None
            def read(self, n):
                return b"x" * min(n, 8)

        class Connection:
            def __init__(self, *args, **kwargs): pass
            def request(self, *args, **kwargs): pass
            def getresponse(self): return Response()
            def close(self): pass

        with patch.object(netguard, "_connection", return_value=Connection()):
            result = netguard.fetch("https://example.com/", max_bytes=16)
        self.assertTrue(result.truncated)
        self.assertLessEqual(len(result.text), 30)


class WebTools(unittest.TestCase):
    SAMPLE = """
    <a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa&amp;rut=x"
       class='result-link'>Example page</a>
    <td class='result-snippet'>Useful <b>text</b> about it.</td>
    """

    def test_lite_parser_and_unwrap(self):
        parser = webtools._ResultParser()
        parser.feed(self.SAMPLE)
        self.assertEqual(len(parser.results), 1)
        self.assertEqual(parser.results[0]["url"], "https://example.org/a")
        self.assertIn("Useful text", parser.results[0]["snippet"])

    def test_search_results_are_re_vetted(self):
        rows = [
            {"title": "Public", "url": "https://example.org/", "snippet": "ok"},
            {"title": "Private", "url": "http://127.0.0.1/admin", "snippet": "no"},
        ]
        kept = webtools._safe_results(rows, 5)
        self.assertEqual([r["title"] for r in kept], ["Public"])

    def test_fetch_page_uses_safe_fetch(self):
        response = netguard.Response(
            url="https://example.org/", status=200, content_type="text/html",
            text="<html><head><title>Demo</title></head><body><script>bad()</script>"
                 "<p>Hello <b>world</b></p></body></html>",
        )
        with patch.object(webtools.netguard, "fetch", return_value=response):
            text = webtools.fetch_page("https://example.org/")
        self.assertIn("Fetched: https://example.org/", text)
        self.assertIn("Title: Demo", text)
        self.assertIn("Hello world", text)
        self.assertNotIn("bad()", text)


class FilesystemTools(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        (self.workspace / "note.txt").write_text("hello")
        self.patch = patch.object(fstools, "CONFIG_FILE", root / "tools.json")
        self.patch.start()
        fstools.configure_workspace(str(self.workspace))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_read_write_list(self):
        self.assertIn("hello", fstools.read("note.txt"))
        self.assertIn("Wrote", fstools.write("sub/new.txt", "new content"))
        self.assertIn("new content", fstools.read("sub/new.txt"))
        self.assertIn("note.txt", fstools.list_dir())

    def test_traversal_and_symlinks_are_refused(self):
        with self.assertRaises(fstools.ToolError):
            fstools.read("../../etc/passwd")
        link = self.workspace / "link"
        link.symlink_to("/etc/passwd")
        with self.assertRaises(fstools.ToolError):
            fstools.read("link")

    def test_secrets_and_binary_are_refused(self):
        with self.assertRaises(fstools.ToolError):
            fstools.write(".env", "API_KEY=abc")
        with self.assertRaises(fstools.ToolError):
            fstools.write("key.pem", "private")
        with self.assertRaises(fstools.ToolError):
            fstools.write("bin.dat", "a\x00b")
        (self.workspace / "binary.bin").write_bytes(b"a\x00b")
        with self.assertRaises(fstools.ToolError):
            fstools.read("binary.bin")


class ToolDispatch(unittest.TestCase):
    def test_new_tools_are_registered(self):
        names = {t["function"]["name"] for t in main.TOOLS}
        self.assertTrue({"web_search", "web_fetch", "filesystem"} <= names)

    def test_run_tool_dispatches(self):
        with patch.object(main.webtools, "format_search", return_value="SEARCH OK"), \
             patch.object(main.webtools, "fetch_page", return_value="FETCH OK"), \
             patch.object(main.fstools, "read", return_value="READ OK"):
            self.assertEqual(main.run_tool("web_search", {"query": "x"}), "SEARCH OK")
            self.assertEqual(main.run_tool("web_fetch", {"url": "https://example.org/"}), "FETCH OK")
            self.assertEqual(main.run_tool("filesystem", {"action": "read", "path": "a"}), "READ OK")


if __name__ == "__main__":
    unittest.main()
