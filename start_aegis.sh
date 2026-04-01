#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Make joblib cache/temp writable to avoid noisy warnings on some systems.
export JOBLIB_TEMP_FOLDER="${JOBLIB_TEMP_FOLDER:-$ROOT_DIR/tmp/joblib}"
mkdir -p "$JOBLIB_TEMP_FOLDER" >/dev/null 2>&1 || true

# Optional local env file.
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PROJECT_VENV="${ROOT_DIR}/venv"
PROJECT_VENV_PY="${PROJECT_VENV}/bin/python"
EXPLICIT_PYTHON_BIN="${AEGIS_PYTHON_BIN:-}"
RESPECT_ACTIVE_VENV="${AEGIS_RESPECT_ACTIVE_VENV:-0}"

API_KEY="${AEGIS_API_KEY:-}"
FILES_KEY="${FILES_API_KEY:-${AEGIS_API_KEY:-}}"
ADMIN_KEY="${ADMIN_API_KEY:-}"

if [[ -z "$API_KEY" ]]; then
  echo "[error] Missing AEGIS_API_KEY. Export it or set it in .env" >&2
  exit 2
fi

if [[ -z "$FILES_KEY" ]]; then
  echo "[error] Missing FILES_API_KEY (or AEGIS_API_KEY fallback)." >&2
  exit 2
fi

PYTHON_BIN="python3"
if [[ -n "$EXPLICIT_PYTHON_BIN" ]]; then
  PYTHON_BIN="$EXPLICIT_PYTHON_BIN"
elif [[ "$RESPECT_ACTIVE_VENV" =~ ^(1|true|yes|on)$ ]] && [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "$PROJECT_VENV_PY" ]]; then
  if [[ "${VIRTUAL_ENV:-}" != "$PROJECT_VENV" && -f "${PROJECT_VENV}/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${PROJECT_VENV}/bin/activate"
  fi
  PYTHON_BIN="$PROJECT_VENV_PY"
elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
fi

RUNTIME_PROFILE="${AEGIS_RUNTIME_PROFILE:-strict}"
PRODUCT_TRACK="${AEGIS_PRODUCT_TRACK:-core}"
CONTRACT_MODE="${AEGIS_START_CONTRACT_MODE:-full}"

exec "$PYTHON_BIN" app/scripts/start_with_preflight.py \
  --runtime-profile "$RUNTIME_PROFILE" \
  --product-track "$PRODUCT_TRACK" \
  --contract-mode "$CONTRACT_MODE" \
  --api-key "$API_KEY" \
  --files-api-key "$FILES_KEY" \
  --admin-api-key "$ADMIN_KEY" \
  "$@"
