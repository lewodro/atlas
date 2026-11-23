"""Guard the ATLAS intro animation against being dropped in a refactor."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Intro(unittest.TestCase):
    def test_markup_present(self):
        html = (ROOT / "web" / "index.html").read_text()
        self.assertIn('<div id="intro" class="intro">', html)
        self.assertIn('<span class="intro-mark">ATLAS</span>', html)

    def test_easeout_keyframes_present(self):
        css = (ROOT / "web" / "style.css").read_text()
        self.assertIn("@keyframes atlas-intro", css)
        self.assertIn("cubic-bezier(0.16, 1, 0.3, 1)", css)
        self.assertIn("scale(1.35)", css)
        self.assertIn("scale(0.45)", css)

    def test_boot_plays_and_removes(self):
        js = (ROOT / "web" / "app.js").read_text()
        self.assertIn('const intro = $("#intro")', js)
        self.assertIn('intro.classList.add("play")', js)
        self.assertIn("intro.remove()", js)
        self.assertIn('has("nointro")', js)


if __name__ == "__main__":
    unittest.main()
