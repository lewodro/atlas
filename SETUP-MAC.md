# Setup — MacBook (the brain's body)

Two roles, pick one:

- **Local only** — model runs here. Simplest, works offline, ~20 tok/s.
- **Client** — model runs on the Windows 2060. Faster, better answers, needs
  the laptop awake and on the same Wi-Fi.

You can switch between them by editing one line.

---

## A. Install

```bash
cd ~/dev/atlas
./install.sh              # system ollama
./install.sh --vendored   # portable ollama inside ./vendor (no brew needed)
```

The installer is idempotent: uv, ollama, the 3B model, and doctor.
It never touches `notes/` or `data/`.

Then:

```bash
ln -sf ~/dev/atlas/atlas ~/.local/bin/atlas
atlas
```

---

## B. Point at the RTX 2060

On the Windows machine, run `install.ps1` — it prints a line like:

```
ATLAS_BASE_URL=http://your-gpu-host:11434/v1
```

Put that in `~/dev/atlas/.env`:

```ini
ATLAS_BASE_URL=http://your-gpu-host:11434/v1
ATLAS_MODEL=qwen2.5:7b
```

Verify from the Mac before blaming Atlas:

```bash
curl http://your-gpu-host:11434/api/version
atlas check
```

`atlas check` will say `running : remote GPU @ http://...`. If the laptop is
asleep you'll get a connection error in ~5 s — that's the trade, and it's why
the 3B stays installed as a fallback.

---

## C. Keep it available without thinking about it

The model server should outlive your terminal:

```bash
brew services start ollama     # already done by install.sh if you used brew
```

For the harness itself, use Terminal tabs or tmux — not a daemon. A chat that
runs forever in the background is a bill with no benefit (see `COSTS.md`).

Nightly consolidation, if you want it:

```bash
# crontab -e
0 3 * * * cd ~/dev/atlas && /opt/homebrew/bin/uv run python consolidate.py >> data/nightly.log 2>&1
```

---

## D. Living inside 8 GB

- The 3B model uses ~2.5 GB while loaded. Ollama unloads it after 5 minutes
  idle (`OLLAMA_KEEP_ALIVE=5m`), so memory comes back.
- Don't run a 7B locally. It will swap and everything gets slower, including
  the editor you're trying to learn in.
- `nomic-embed-text` (274 MB) stays loaded during a session; it's how recall
  finds "studying" when the note says "learning". If it's missing, Atlas
  silently falls back to keyword search.
- Close Chrome tabs before a big `atlas sleep`.

Check what's actually resident:

```bash
ollama ps
```

---

## E. Troubleshooting

| Symptom | Fix |
|---|---|
| `Connection refused` | `brew services start ollama`, or re-run `./install.sh` |
| Works on Windows, not here | wrong IP, firewall, or laptop asleep |
| Answers but never remembers | `atlas check` → "memory extraction" line |
| Recall feels dumb | `ollama pull nomic-embed-text`, then `atlas eval` |
| Slow first answer | model loading, ~5–10 s; later turns are fast |
| `uv: command not found` | `brew install uv` |
