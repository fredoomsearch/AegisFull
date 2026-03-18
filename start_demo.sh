#!/usr/bin/env bash
set -euo pipefail

# Fast, clean demo launcher (no uvicorn --reload; minimal warmups).
#
# Uses the same gates as start_aegis.sh, but avoids long startup warmups that
# are great for production but slow down interview demos.
#
# Usage:
#   export AEGIS_API_KEY="..."
#   export FILES_API_KEY="..."   # optional, defaults to AEGIS_API_KEY
#   export ADMIN_API_KEY="..."   # optional, defaults to AEGIS_API_KEY
#   ./start_demo.sh
#
# Optional:
#   ./start_demo.sh --skip-browser-smoke
#
# Notes:
# - DEMO_MODE disables startup LLM warmup + web warmup thread.
# - First real chat message may take longer if the model loads on-demand.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Make joblib cache/temp writable to avoid noisy warnings on some systems.
export JOBLIB_TEMP_FOLDER="${JOBLIB_TEMP_FOLDER:-$ROOT_DIR/tmp/joblib}"
mkdir -p "$JOBLIB_TEMP_FOLDER" >/dev/null 2>&1 || true

if [[ -f ".env.demo" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.demo"
  set +a
elif [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

if [[ -z "${VIRTUAL_ENV:-}" && -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

export AEGIS_DEMO_MODE=1
export AEGIS_LLM_WARMUP=0
export AEGIS_WEB_WARMUP=0

API_KEY="${AEGIS_API_KEY:-}"
FILES_KEY="${FILES_API_KEY:-${AEGIS_API_KEY:-}}"
ADMIN_KEY="${ADMIN_API_KEY:-${AEGIS_API_KEY:-}}"

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

exec "$PYTHON_BIN" app/scripts/start_with_preflight.py \
  --api-key "$API_KEY" \
  --files-api-key "$FILES_KEY" \
  --admin-api-key "$ADMIN_KEY" \
  "$@"
