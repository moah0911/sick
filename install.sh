#!/usr/bin/env bash
# Sick — self-improving coding agent. Idempotent installer.
#
#   ./install.sh              local dev install: uv sync + ~/.local/bin/sick shim
#   ./install.sh --global     global install: `uv tool install` (sick on PATH anywhere)
#   ./install.sh --with-video also install the Remotion skills for /visual
#   ./install.sh --uninstall  remove the shim / global tool
set -euo pipefail

log() { printf '\033[1;34m[sick]\033[0m %s\n' "$*"; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# the `nooa` git dependency carries Git-LFS example artifacts that installs
# don't need; skipping the smudge keeps clones working without git-lfs
export GIT_LFS_SKIP_SMUDGE="${GIT_LFS_SKIP_SMUDGE:-1}"

MODE="local"
WITH_VIDEO=0
for arg in "$@"; do
  case "$arg" in
    --global) MODE="global" ;;
    --uninstall) MODE="uninstall" ;;
    --with-video) WITH_VIDEO=1 ;;
    -h|--help) grep '^#' "$0" | head -n 8; exit 0 ;;
    *) log "unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

ensure_uv() {
  if ! command -v uv >/dev/null 2>&1; then
    log "uv not found — installing via the official installer"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
}

if [ "$MODE" = "uninstall" ]; then
  TARGET="$HOME/.local/bin/sick"
  if [ -L "$TARGET" ]; then
    DEST="$(readlink "$TARGET")"
    case "$DEST" in *"$ROOT"*) rm "$TARGET"; log "removed shim $TARGET" ;; *) log "leaving $TARGET (points elsewhere: $DEST)" ;; esac
  fi
  if command -v uv >/dev/null 2>&1; then
    uv tool uninstall sick >/dev/null 2>&1 && log "removed global uv tool 'sick'" || true
  fi
  log "uninstalled. (checkout and ~/.sick data left untouched)"
  exit 0
fi

ensure_uv
# only download a Python when none is available (keeps re-runs offline-safe)
if ! uv python find 3.13 >/dev/null 2>&1; then
  uv python install 3.13
fi

if [ "$MODE" = "global" ]; then
  log "installing sick globally via uv tool (isolated env, works from any directory)"
  uv tool install --force --from "$ROOT" sick
  if command -v sick >/dev/null 2>&1; then
    sick --version
  else
    log "WARNING: sick not on PATH — uv tool bin dir is usually ~/.local/bin"
    log "add it: export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
else
  log "syncing dependencies"
  uv sync

  if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env 2>/dev/null || true
    log "created .env (600) — set one of NVIDIA_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY"
  else
    log ".env already exists — leaving it untouched"
  fi

  mkdir -p "$HOME/.local/bin"
  TARGET="$HOME/.local/bin/sick"
  if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
    log "WARNING: $TARGET exists and is not a symlink — leaving it untouched"
  else
    ln -sfn "$ROOT/bin/sick" "$TARGET"
    log "linked $TARGET -> $ROOT/bin/sick"
  fi
  case ":$PATH:" in
    *":$HOME/.local/bin:"*) ;;
    *) log "WARNING: ~/.local/bin not on PATH — add: export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
  esac
fi

if [ "$WITH_VIDEO" = "1" ]; then
  log "installing remotion skills (requires Node.js)"
  npx skills add remotion-dev/skills@remotion-create -g -y
  npx skills add remotion-dev/skills@remotion-best-practices -g -y
fi

log "running preflight"
if [ -x "$ROOT/.venv/bin/sick" ]; then
  "$ROOT/.venv/bin/sick" --preflight || log "preflight found issues — see the report above"
elif command -v sick >/dev/null 2>&1; then
  sick --preflight || log "preflight found issues — see the report above"
else
  log "skipping preflight (no sick binary yet)"
fi

log "done. Run: sick"
