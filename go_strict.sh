#!/usr/bin/env bash
set -euo pipefail

# One-command strict GO/NO-GO:
# 1) Check production posture (keys/cors/hsts/av + browser + image endpoint reachability)
# 2) Run strict verify_full (includes strict readyz/e2e/browser smoke)
#
# Usage:
#   ./go_strict.sh --base-url http://127.0.0.1:8000
#
# Optional env:
#   AEGIS_BROWSER_SMOKE_CMD="python -m app.scripts.browser_smoke --base-url http://127.0.0.1:8000 --api-key ... --files-api-key ... --strict"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env.production" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.production"
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

PYTHON_BIN="python3"
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
  PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${ROOT_DIR}/venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
fi

export AEGIS_RUNTIME_PROFILE=strict
export AEGIS_PRODUCT_TRACK=full

echo "[check] production-profile"
"$PYTHON_BIN" -m app.scripts.production_profile_check --require-browser --require-image-endpoint

echo "[check] verify-full-strict"
exec "$PYTHON_BIN" -m app.scripts.verify_full \
  --runtime-profile strict \
  --product-track full \
  --strict-browser-smoke \
  "$@"
