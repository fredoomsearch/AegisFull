
0.#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Optional local env file.
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

# Optional local virtualenv.
if [[ -z "${VIRTUAL_ENV:-}" && -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

API_KEY="${AEGIS_API_KEY:-}"
FILES_KEY="${FILES_API_KEY:-${AEGIS_API_KEY:-}}"
ADMIN_KEY="${ADMIN_API_KEY:-${AEGIS_API_KEY:-}}"

if [[ -z "$API_KEY" ]]; then
  echo "[error] Missing AEGIS_API_KEY. Export it or set it in .env" >&2
  exit 2
fi

if [[ -z "$FILES_KEY" ]]; then
  echo "[error] Missing FILES_API_KEY (or AEGIS_API_KEY fallback)." >&2
  exit 2
fi

exec python3 app/scripts/start_with_preflight.py \
  --reload \
  --api-key "$API_KEY" \
  --files-api-key "$FILES_KEY" \
  --admin-api-key "$ADMIN_KEY" \
  "$@"
