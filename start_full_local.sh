#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# Optional local strict/full env file.
if [[ -f ".env.strict.full.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env.strict.full.local"
  set +a
fi

# Activate local venv if not active.
if [[ -z "${VIRTUAL_ENV:-}" && -f "venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "venv/bin/activate"
fi

# strict/full
export AEGIS_RUNTIME_PROFILE="${AEGIS_RUNTIME_PROFILE:-strict}"
export AEGIS_PRODUCT_TRACK="${AEGIS_PRODUCT_TRACK:-full}"
export AEGIS_AUTH_MODE="${AEGIS_AUTH_MODE:-on}"

# required keys
export AEGIS_API_KEY="${AEGIS_API_KEY:-aegis-demo-key-2026-strong}"
export FILES_API_KEY="${FILES_API_KEY:-$AEGIS_API_KEY}"
export ADMIN_API_KEY="${ADMIN_API_KEY:-set-a-different-strong-key}"

# DB + image + browser
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/aegis}"
export AEGIS_IMAGE_ENDPOINT="${AEGIS_IMAGE_ENDPOINT:-http://127.0.0.1:8188/prompt}"
export AEGIS_IMAGE_CKPT="${AEGIS_IMAGE_CKPT:-DreamShaper_8_pruned.safetensors}"
export AEGIS_IMAGE_TIMEOUT="${AEGIS_IMAGE_TIMEOUT:-90}"
export AEGIS_BROWSER_BINARY="${AEGIS_BROWSER_BINARY:-/usr/bin/google-chrome-stable}"

# strict security defaults
export AEGIS_CORS_ORIGINS="${AEGIS_CORS_ORIGINS:-http://127.0.0.1:8000}"
export FILES_AV_FAIL_OPEN="${FILES_AV_FAIL_OPEN:-0}"
export AEGIS_HSTS_SECONDS="${AEGIS_HSTS_SECONDS:-31536000}"

# runtime stability
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

echo "[profile] runtime=${AEGIS_RUNTIME_PROFILE} track=${AEGIS_PRODUCT_TRACK} auth=${AEGIS_AUTH_MODE}"
echo "[env] image_endpoint=${AEGIS_IMAGE_ENDPOINT} browser=${AEGIS_BROWSER_BINARY}"
echo "[env] cors=${AEGIS_CORS_ORIGINS} av_fail_open=${FILES_AV_FAIL_OPEN} hsts=${AEGIS_HSTS_SECONDS}"

exec ./start_aegis.sh "$@"
