#!/bin/sh
# Atlas installer for macOS.
#
#   ./install.sh              use Ollama already on this machine
#   ./install.sh --vendored   keep Ollama inside ./vendor (portable, no brew)
#   ./install.sh --pull qwen2.5:7b
#
# Safe to re-run. It never touches your notes or data.

set -eu
cd "$(dirname "$0")"

MODEL="${ATLAS_MODEL:-qwen2.5:3b}"
VENDORED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --vendored) VENDORED=1 ;;
    --pull) shift; MODEL="$1" ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- python
say "1/5  python tooling"
if ! command -v uv >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
uv sync
echo "     uv $(uv --version | awk '{print $2}')"

# ---------------------------------------------------------------- ollama
say "2/5  ollama"
OLLAMA_BIN=""

if [ "$VENDORED" = "1" ] || [ -x "vendor/ollama/ollama" ]; then
  if [ ! -x "vendor/ollama/ollama" ]; then
    echo "     downloading portable ollama (~180 MB)…"
    mkdir -p vendor
    curl -L --fail -o vendor/ollama-darwin.tgz https://ollama.com/download/ollama-darwin.tgz
    rm -rf vendor/ollama && mkdir -p vendor/ollama
    tar -xzf vendor/ollama-darwin.tgz -C vendor/ollama
    rm -f vendor/ollama-darwin.tgz
  fi
  OLLAMA_BIN="$(pwd)/vendor/ollama/ollama"
elif command -v ollama >/dev/null 2>&1; then
  OLLAMA_BIN="$(command -v ollama)"
elif command -v brew >/dev/null 2>&1; then
  brew install ollama
  OLLAMA_BIN="$(command -v ollama)"
else
  echo "     no ollama and no brew. re-run with --vendored"; exit 1
fi
echo "     $OLLAMA_BIN"

# ---------------------------------------------------------------- server
say "3/5  server"
if curl -sf http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "     already running"
else
  echo "     starting in the background (log: data/ollama.log)"
  mkdir -p data
  nohup "$OLLAMA_BIN" serve > data/ollama.log 2>&1 &
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    curl -sf http://127.0.0.1:11434/api/version >/dev/null 2>&1 && break
    sleep 1
  done
  echo "     up"
fi

# ---------------------------------------------------------------- model
say "4/5  model ($MODEL)"
"$OLLAMA_BIN" pull "$MODEL"
grep -q '^ATLAS_MODEL=' .env 2>/dev/null || echo "ATLAS_MODEL=$MODEL" >> .env
grep -q '^ATLAS_BASE_URL=' .env 2>/dev/null || echo "ATLAS_BASE_URL=http://127.0.0.1:11434/v1" >> .env

# ---------------------------------------------------------------- verify
say "5/5  verify"
uv run python check.py

say "done"
echo "  start:   uv run python main.py"
echo "  or:      ln -sf \"$(pwd)/atlas\" ~/.local/bin/atlas && atlas"
echo "  memory:  atlas remember \"I ...\"  (or just tell Atlas in chat)"
