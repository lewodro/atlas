# Running Atlas on a server

Atlas is local-first by default. It has **no built-in accounts, passwords or
multi-tenant isolation**. If you put it on a machine other people can reach,
you must add authentication at the network layer (VPN or reverse proxy). Do
not expose `:7777` directly to the internet.

## 1. One machine, one Atlas

```bash
# prerequisites: uv, Python 3.12+, a local model runtime if you want local AI
git clone https://github.com/lewodro/atlas.git
cd atlas
uv sync
cp .env.example .env          # edit provider/model settings
uv run python server.py --port 7777
```

Open `http://localhost:7777`. For a remote machine, keep the bind local and
use an SSH tunnel:

```bash
ssh -L 7777:127.0.0.1:7777 user@server
```

That is the simplest secure setup: no public port, no auth needed.

## 2. Persistent systemd service (Linux)

`/etc/systemd/system/atlas.service`:

```ini
[Unit]
Description=Atlas agent harness
After=network-online.target

[Service]
Type=simple
User=atlas
WorkingDirectory=/opt/atlas
Environment=ATLAS_DATA_DIR=/var/lib/atlas/data
Environment=ATLAS_SHARED_DRIVE=/srv/atlas-shared
Environment=ATLAS_WORKSPACE=/srv/atlas-workspace
ExecStart=/home/atlas/.local/bin/uv run python server.py --port 7777
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now atlas
journalctl -u atlas -f
```

On macOS use `launchd` with the same environment, or simply
`brew services start ollama` plus `uv run python server.py --stay-open`.

## 3. Several agents, one united drive

From the **Harness** tab in Settings, or the CLI:

```bash
atlas fleet create Builder /srv/atlas-workspace --provider ollama --model qwen2.5:3b
atlas fleet create Researcher /srv/atlas-workspace --provider openrouter --model openai/gpt-4o-mini
atlas fleet start <id>
atlas fleet list
atlas fleet goal "Write a shared report about the project"
atlas fleet tournament "Which design is best?"
```

Each instance is its own process with isolated memory, workspace, model,
provider, port and egress ledger. They all share `ATLAS_SHARED_DRIVE`:

```bash
export ATLAS_SHARED_DRIVE=/srv/atlas-shared
```

Put that on a persistent disk or a mounted NFS/SMB share. Agents use the
`share` tool to list/read/write files and append to `HANDOFF.md`. The web UI
shows a change bar at the bottom and a browsable united drive in the Harness
tab.

## 4. HTTPS + authentication (required for a real server)

Use a reverse proxy in front of Atlas, with TLS and a real login. Example with
Caddy + basic auth (replace with SSO/OIDC for a team):

```caddyfile
atlas.example.com {
  basicauth {
    you $2a$14$...       # caddy hash-password
  }
  reverse_proxy 127.0.0.1:7777
}
```

For multiple instances, give each a route or hostname:

```caddyfile
builder.example.com    { reverse_proxy 127.0.0.1:7800 }
research.example.com   { reverse_proxy 127.0.0.1:7801 }
```

If you use SSH tunnels or a WireGuard/Tailscale VPN instead, you can skip the
public proxy entirely — that is the recommended default.

## 5. Local + frontier models

Local runtimes stay on the machine: Ollama, LM Studio, llama.cpp, vLLM. Hosted
API keys go in `.env` (never in tracked source):

```bash
OPENROUTER_API_KEY=...
ATLAS_FRONTIER_BASE_URL=https://openrouter.ai/api/v1
ATLAS_FRONTIER_API_KEY=...
ATLAS_FRONTIER_MODEL=openai/gpt-4o-mini
```

Then:

- `atlas bridge "question"` — local model writes the brief, frontier answers.
- `atlas codebridge "build a CLI parser"` — local model writes the spec,
  frontier writes complete files, the harness compiles/runs them locally.
- The web UI records every outbound call in `data/egress.jsonl`; inspect with
  `atlas models --egress`.

## 6. Backups and portability

Back up these paths:

- `data/atlas.db` (memory, tool policy, feedback, forged skills)
- `data/shared` (the united drive)
- `notes/` (personal Markdown notes)
- `.env` (keys — store it securely, not in Git)

Export learned tool behaviour with `atlas policy --export backup.json` and
restore on another machine with `atlas policy --import backup.json`.

## Security notes

- The terminal tool is an allowlist, not a shell. File tools are confined to
  the workspace; the `share` tool is confined to the united drive.
- External web text is treated as untrusted data, never instructions.
- Remote model endpoints are blocked until a preset is selected or
  `ATLAS_ALLOW_REMOTE=1` is set.
- Atlas has **no multi-user permissions**. Treat every authenticated proxy
  user as an administrator of that instance.
