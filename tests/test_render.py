"""Tests for the offline markdown/math renderer (runs the real JS module)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Renderer(unittest.TestCase):
    def render(self, text: str) -> str:
        script = (
            "const r=require(process.argv[1]);"
            "process.stdout.write(r.renderMarkdown(process.argv[2]));"
        )
        result = subprocess.run(
            ["node", "-e", script, str(ROOT / "web" / "render.js"), text],
            capture_output=True, text=True, check=True,
        )
        return result.stdout

    def test_inline_math(self):
        out = self.render(r"Study \(f(x)=x^2\) now.")
        self.assertIn("class=\"math\"", out)
        self.assertIn("x²", out)
        self.assertNotIn("\\(", out)

    def test_display_math_and_fraction(self):
        out = self.render("\[\\int_0^1 \\frac{x^2}{2} dx\]")
        self.assertIn("math-block", out)
        self.assertIn("∫", out)
        self.assertIn("(x²)/(2)", out)

    def test_markdown_structure(self):
        out = self.render("## Title\n\n- **bold** item\n- `code` item\n\n1. first\n2. second")
        self.assertIn("<h2>", out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<code>code</code>", out)
        self.assertIn("<ol>", out)

    def test_fake_images_are_removed(self):
        out = self.render("![Quadratic Plot](#)")
        self.assertNotIn("<img", out)
        self.assertNotIn("Quadratic Plot", out)

    def test_code_fence_is_escaped(self):
        out = self.render("```python\nprint('<x>')\n```")
        self.assertIn("<pre><code>", out)
        self.assertIn("&lt;x&gt;", out)

    def test_links_are_safe(self):
        out = self.render("[docs](javascript:alert(1)) and [ok](https://example.org)")
        self.assertNotIn("javascript:", out)
        self.assertIn("https://example.org", out)


if __name__ == "__main__":
    unittest.main()
