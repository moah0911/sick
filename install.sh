#!/usr/bin/env bash
# Sick — self-improving coding agent. Idempotent installer.
set -euo pipefail

log() { printf '\033[1;34m[sick]\033[0m %s\n' "$*"; }

# 1. Python 3.13+ and uv
if ! command -v uv >/dev/null 2>&1; then
  log "uv not found — installing via the official installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv python ensure 3.13

# 2. Dependencies
log "syncing dependencies"
uv sync

# 3. Environment file
if [ ! -f .env ]; then
  cp .env.example .env
  log "created .env — set one of NVIDIA_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY"
else
  log ".env already exists — leaving it untouched"
fi

# 4. Optional: remotion skills for /visual (requires Node.js)
if [ "${1:-}" = "--with-video" ]; then
  log "installing remotion skills (requires Node.js)"
  npx skills add remotion-dev/skills@remotion-create -g -y
  npx skills add remotion-dev/skills@remotion-best-practices -g -y
fi

# 5. Health check
log "running preflight"
uv run sick --preflight || log "preflight found issues — see the report above"

log "done. Run: uv run sick"