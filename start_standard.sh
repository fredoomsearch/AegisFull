#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Optional demo profile env loader.
if [[ -f ".env.demo" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.demo"
  set +a
fi

export AEGIS_RUNTIME_PROFILE=standard

exec ./start_aegis.sh "$@"
