#!/usr/bin/env bash
set -euo pipefail

# Clean stop helper for local dev/demo without hunting processes manually.
#
# Usage:
#   export ADMIN_API_KEY="..."            # required if shutdown endpoint enabled
#   export AEGIS_BASE_URL="http://127.0.0.1:8000"   # optional
#   ./stop_aegis.sh
#   ./stop_aegis.sh --clean
#   ./stop_aegis.sh --aggressive-clean
#
# Notes:
# - If AEGIS_ENABLE_SHUTDOWN_ENDPOINT=1 on the server, this will call /system/shutdown.
# - Otherwise it falls back to killing a local uvicorn process bound to the default port.

BASE_URL="${AEGIS_BASE_URL:-http://127.0.0.1:8000}"
ADMIN_KEY="${ADMIN_API_KEY:-}"
CLEAN_ARTIFACTS=0
AGGRESSIVE_CLEAN=0

for arg in "$@"; do
  case "$arg" in
    --clean|--clean-artifacts)
      CLEAN_ARTIFACTS=1
      ;;
    --aggressive-clean)
      CLEAN_ARTIFACTS=1
      AGGRESSIVE_CLEAN=1
      ;;
  esac
done

if [[ -n "$ADMIN_KEY" ]]; then
  echo "[stop] POST ${BASE_URL}/system/shutdown (best-effort)"
  if curl -fsS -X POST "${BASE_URL}/system/shutdown" -H "X-API-Key: ${ADMIN_KEY}" >/dev/null 2>&1; then
    echo "[stop] Shutdown requested."
    # continue: optional local cleanup may still be requested.
  fi
fi

echo "[stop] Shutdown endpoint unavailable (or ADMIN_API_KEY missing); falling back to process kill (best-effort)."

# Stop the preflight orchestrator (if it is running in the background).
if command -v pkill >/dev/null 2>&1; then
  pkill -u "$(id -u)" -f "app/scripts/start_with_preflight.py" >/dev/null 2>&1 || true
fi

# Kill uvicorn on the default app/port if present (current user only).
if command -v pkill >/dev/null 2>&1; then
  pkill -u "$(id -u)" -f "uvicorn main:app" >/dev/null 2>&1 || true
  pkill -u "$(id -u)" -f "python.*-m uvicorn main:app" >/dev/null 2>&1 || true
fi

# Also kill anything still bound to the port (Linux tools optional).
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp >/dev/null 2>&1 || true
fi

# Browser smoke leftovers (best-effort).
if command -v pkill >/dev/null 2>&1; then
  pkill -u "$(id -u)" -f "chromedriver" >/dev/null 2>&1 || true
  # Don't kill the user's normal browser session; target headless/test invocations only.
  pkill -u "$(id -u)" -f "brave.*--headless" >/dev/null 2>&1 || true
  pkill -u "$(id -u)" -f "chrome.*--headless" >/dev/null 2>&1 || true
  pkill -u "$(id -u)" -f "chromium.*--headless" >/dev/null 2>&1 || true
  pkill -u "$(id -u)" -f "chrome.*--remote-debugging-port" >/dev/null 2>&1 || true
fi

echo "[stop] Done."

if [[ "$CLEAN_ARTIFACTS" == "1" ]]; then
  echo "[clean] Removing runtime artifacts..."
  PYTHON_BIN="python3"
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
  elif [[ -x "${PWD}/venv/bin/python" ]]; then
    PYTHON_BIN="${PWD}/venv/bin/python"
  fi
  CLEAN_CMD=("$PYTHON_BIN" -m app.scripts.cleanup_runtime_artifacts)
  if [[ "$AGGRESSIVE_CLEAN" == "1" ]]; then
    CLEAN_CMD+=(--aggressive)
  fi
  "${CLEAN_CMD[@]}" || true
fi
