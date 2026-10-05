#!/usr/bin/env bash
# Runs the meeting-transcriber CLI from wherever this skill is installed. All arguments are passed through.
#   - inside the full repo (git clone, or Claude Code plugin): runs the bundled code with the locked dependencies
#   - standalone skill folder (npx skills add, manual copy): runs the pinned release via uvx
set -euo pipefail

# v0.1.1, pinned by commit: a tag needs the network to resolve, a commit lets uvx reuse its cache offline
RELEASE="${MEETING_TRANSCRIBER_SPEC:-git+https://github.com/Vovamujik/meeting-transcriber@a8d531412331ff7a71b952c057674cf53c497e31}"
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
ROOT="$(cd "$SKILL_DIR/../.." && pwd -P)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 127
fi

if grep -qs '^name = "meeting-transcriber"' "$ROOT/pyproject.toml"; then
  if [ ! -d "$ROOT/.venv" ]; then
    # Plugin installs live in a versioned cache dir that is replaced on update: keep the venv outside of it.
    export UV_PROJECT_ENVIRONMENT="${MEETING_TRANSCRIBER_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/meeting-transcriber}/venv"
  fi
  exec uv run --frozen --project "$ROOT" meeting-transcriber "$@"
fi
# Prefer the cached environment (works offline, no GitHub round-trip); fetch the release only if it isn't cached yet.
if uvx --offline --from "$RELEASE" meeting-transcriber --version >/dev/null 2>&1; then
  exec uvx --offline --from "$RELEASE" meeting-transcriber "$@"
fi
exec uvx --from "$RELEASE" meeting-transcriber "$@"
