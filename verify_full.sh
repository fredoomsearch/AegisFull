#!/usr/bin/env bash
set -euo pipefail

# Extended verification helper:
# - full pytest
# - strict host E2E (capabilities)
# - agent evals
# - browser smoke (if browser runtime is available)
#
# Usage:
#   export AEGIS_API_KEY="..."
#   export FILES_API_KEY="..."   # optional, defaults to AEGIS_API_KEY
#   ./start_aegis.sh             # in another terminal
#   ./verify_full.sh --base-url http://127.0.0.1:8000

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if [[ -z "${VIRTUAL_ENV:-}" && -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

API_KEY="${AEGIS_API_KEY:-}"
FILES_KEY="${FILES_API_KEY:-${AEGIS_API_KEY:-}}"

if [[ -z "$API_KEY" ]]; then
  echo "[error] Missing AEGIS_API_KEY. Export it or set it in .env" >&2
  exit 2
fi

PYTHON_BIN="python3"
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
fi

RUNTIME_PROFILE="${AEGIS_RUNTIME_PROFILE:-strict}"
PRODUCT_TRACK="${AEGIS_PRODUCT_TRACK:-core}"

exec "$PYTHON_BIN" -m app.scripts.verify_full \
  --runtime-profile "$RUNTIME_PROFILE" \
  --product-track "$PRODUCT_TRACK" \
  --api-key "$API_KEY" \
  --files-api-key "$FILES_KEY" \
  "$@"
