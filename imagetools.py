"""Local SVG image tools — deterministic, text-based, no external service.

Generated images are real SVG files in the workspace and are registered as
artifacts so the GUI can preview them. Edits are simple, explicit operations
(background, caption, scale) on an existing SVG.
"""

from __future__ import annotations

import hashlib
import html
import re

import fstools

PALETTES = [
    ("#0b0f14", "#22d3a6", "#e9eef3"),
    ("#0a0712", "#b18cff", "#f2eefb"),
    ("#050505", "#ffffff", "#b0b0b0"),
    ("#020403", "#5fbf87", "#ebf2ec"),
]


def available() -> bool:
    return True


def _seed(prompt: str) -> int:
    return int(hashlib.sha256(prompt.encode()).hexdigest()[:8], 16)


def generate(args: dict) -> dict:
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise fstools.ToolError("prompt is empty")
    path = str(args.get("path") or "images/atlas-image.svg").strip()
    title = str(args.get("title") or prompt[:48]).strip()
    seed = _seed(prompt)
    bg, accent, fg = PALETTES[seed % len(PALETTES)]
    safe_title = html.escape(title[:60])

    circles = []
    for index in range(5):
        cx = 110 + ((seed >> (index * 4)) % 380)
        cy = 90 + ((seed >> (index * 6)) % 240)
        radius = 20 + ((seed >> (index * 3)) % 60)
        opacity = 0.08 + ((seed >> index) % 12) / 100
        circles.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{accent}" opacity="{opacity:.2f}"/>'
        )

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">
<rect width="640" height="400" fill="{bg}"/>
{''.join(circles)}
<path d="M40 300 Q160 180 300 260 T600 170" fill="none" stroke="{accent}" stroke-width="3" opacity="0.75"/>
<text x="40" y="70" fill="{fg}" font-family="monospace" font-size="22">{safe_title}</text>
<text x="40" y="350" fill="{accent}" font-family="monospace" font-size="12">generated locally by atlas</text>
</svg>'''
    fstools.write(path, svg)
    return {
        "ok": True,
        "data": f"Generated SVG image at {path} from prompt: {prompt[:100]}",
        "artifact_hint": {"title": title, "kind": "image", "path": path},
    }


def edit(args: dict) -> dict:
    path = str(args.get("path") or "").strip()
    if not path:
        raise fstools.ToolError("path is required")
    raw = fstools.read(path, max_chars=100000)
    svg = raw.split(":\n", 1)[-1]
    if "<svg" not in svg or "</svg>" not in svg:
        raise fstools.ToolError("target is not an SVG image")

    background = str(args.get("background") or "").strip()
    if background and re.match(r"^#[0-9a-fA-F]{6}$", background):
        svg = re.sub(
            r'(<rect[^>]*?)fill="[^"]*"',
            f'\\1fill="{background}"',
            svg, count=1,
        )
    caption = str(args.get("caption") or "").strip()
    if caption:
        safe = html.escape(caption[:60])
        svg = re.sub(
            r'<text[^>]*font-size="12"[^>]*>[^<]*</text>',
            f'<text x="40" y="350" fill="#22d3a6" font-family="monospace" font-size="12">{safe}</text>',
            svg,
        )
    scale = args.get("scale")
    if scale:
        factor = max(0.25, min(float(scale), 4.0))
        svg = re.sub(r'width="\d+" height="\d+"',
                     f'width="{int(640 * factor)}" height="{int(400 * factor)}"',
                     svg, count=1)

    fstools.write(path, svg)
    return {
        "ok": True,
        "data": f"Updated image {path}",
        "artifact_hint": {"title": path, "kind": "image", "path": path},
    }
