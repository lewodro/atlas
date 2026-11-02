"""Settings. Read once, from .env or the environment.

Everything that differs between "running on the MacBook" and "running on the
Windows laptop with the RTX 2060" is one line in .env:

    ATLAS_BASE_URL=http://192.168.1.42:11434/v1
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent


def load_env(path: Path = ROOT / ".env") -> None:
    """Tiny .env reader, so you don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()

BASE_URL = os.getenv("ATLAS_BASE_URL", "http://127.0.0.1:11434/v1")
API_KEY = os.getenv("ATLAS_API_KEY", "ollama")

#: True when the model lives on the other machine.
REMOTE = not any(h in BASE_URL for h in ("127.0.0.1", "localhost"))

#: A 3B model fits in 8 GB of unified memory; a 7B does not.
MODEL = os.getenv("ATLAS_MODEL") or (
    "qwen2.5:7b" if REMOTE else "qwen2.5:3b"
)

WHERE = f"{'remote GPU' if REMOTE else 'this machine'} @ {BASE_URL}"
ROOT_NOTES = ROOT / "notes"
ROOT_DATA = ROOT / "data"

# ---------------------------------------------------------------- frontier
# Optional second tier: a cloud model for the hard questions, while the local
# model keeps doing the cheap routine work. Leave these blank to disable.
#
#   ATLAS_FRONTIER_BASE_URL=https://api.deepseek.com/v1
#   ATLAS_FRONTIER_API_KEY=sk-...
#   ATLAS_FRONTIER_MODEL=deepseek-chat
#
FRONTIER_BASE_URL = os.getenv("ATLAS_FRONTIER_BASE_URL", "")
FRONTIER_API_KEY = os.getenv("ATLAS_FRONTIER_API_KEY", "")
FRONTIER_MODEL = os.getenv("ATLAS_FRONTIER_MODEL", "")
FRONTIER_READY = bool(FRONTIER_BASE_URL and FRONTIER_API_KEY and FRONTIER_MODEL)
