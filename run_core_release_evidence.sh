#!/usr/bin/env bash
set -euo pipefail

# Core-track strict evidence bundle runner.
# What it does:
# - Runs strict core-track doctor/verify/hard-contract checks against a live host.
# - Archives machine-readable evidence under artifacts/release_evidence_core/<timestamp>/.
#
# Why it exists:
# - Milestone A requires one host-level archived strict/core artifact bundle.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BASE_URL="${AEGIS_BASE_URL:-http://127.0.0.1:8000}"
OUT_ROOT="${AEGIS_CORE_EVIDENCE_DIR:-artifacts/release_evidence_core}"
WINDOW_SECONDS="${AEGIS_CONTRACT_WINDOW_SECONDS:-900}"
RUN_SOAK=0
DURATION_HOURS="${AEGIS_SOAK_HOURS:-4}"
PRECHECK_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --out-dir)
      OUT_ROOT="$2"
      shift 2
      ;;
    --window-seconds)
      WINDOW_SECONDS="$2"
      shift 2
      ;;
    --run-soak)
      RUN_SOAK=1
      shift
      ;;
    --duration-hours)
      DURATION_HOURS="$2"
      shift 2
      ;;
    --precheck-only)
      PRECHECK_ONLY=1
      shift
      ;;
    *)
      echo "[error] Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

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

API_KEY="${AEGIS_API_KEY:-}"
FILES_KEY="${FILES_API_KEY:-${AEGIS_API_KEY:-}}"

if [[ -z "$API_KEY" ]]; then
  echo "[error] Missing AEGIS_API_KEY for evidence run." >&2
  exit 2
fi

TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${OUT_ROOT}/${TS}"
mkdir -p "$OUT_DIR"

export AEGIS_RUNTIME_PROFILE=strict
export AEGIS_PRODUCT_TRACK=core

echo "[info] core strict evidence run"
echo "  base_url=${BASE_URL}"
echo "  out_dir=${OUT_DIR}"
echo "  run_soak=${RUN_SOAK}"
echo "  duration_hours=${DURATION_HOURS}"
echo "  precheck_only=${PRECHECK_ONLY}"

echo "[run] doctor (core)"
if ! "$PYTHON_BIN" -m app.scripts.doctor \
  --track core \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --json \
  | tee "${OUT_DIR}/doctor_core.json"; then
  echo "[fail] core doctor precheck failed. Resolve core runtime blockers and retry." >&2
  if [[ -s "${OUT_DIR}/doctor_core.json" ]]; then
    echo "[detail] doctor blockers:" >&2
    "$PYTHON_BIN" - "${OUT_DIR}/doctor_core.json" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    checks = payload.get("checks") if isinstance(payload, dict) else []
    for chk in checks or []:
        if not bool(chk.get("ok")):
            name = chk.get("name") or "unknown"
            detail = chk.get("detail") or ""
            print(f"  - {name}: {detail}")
except Exception as exc:  # noqa: BLE001
    print(f"  - unable to parse doctor output ({exc})")
PY
  fi
  echo "[hint] Re-run: python -m app.scripts.doctor --track core --base-url ${BASE_URL}" >&2
  exit 2
fi

if [[ "$PRECHECK_ONLY" == "1" ]]; then
  echo "[run] precheck snapshot"
  curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/readyz" > "${OUT_DIR}/system_readyz.json"
  curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/metrics?window_seconds=${WINDOW_SECONDS}" > "${OUT_DIR}/system_metrics.json"
  cat > "${OUT_DIR}/run_meta.txt" <<EOF
timestamp=${TS}
base_url=${BASE_URL}
runtime_profile=strict
product_track=core
mode=precheck-only
window_seconds=${WINDOW_SECONDS}
EOF
  echo "[ok] core precheck bundle ready: ${OUT_DIR}"
  exit 0
fi

echo "[run] verify_full (strict/core)"
"$PYTHON_BIN" -m app.scripts.verify_full \
  --runtime-profile strict \
  --product-track core \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --files-api-key "$FILES_KEY" \
  | tee "${OUT_DIR}/verify_full_core.log"

echo "[run] hard_contract_check (strict/core)"
"$PYTHON_BIN" -m app.scripts.hard_contract_check \
  --strict \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --run-no-loop \
  --window-seconds "$WINDOW_SECONDS" \
  | tee "${OUT_DIR}/hard_contract_core.log"

if [[ "$RUN_SOAK" == "1" ]]; then
  echo "[run] soak_gate (${DURATION_HOURS}h)"
  "$PYTHON_BIN" -m app.scripts.soak_gate \
    --base-url "$BASE_URL" \
    --api-key "$API_KEY" \
    --duration-hours "$DURATION_HOURS" \
    --window-seconds "$WINDOW_SECONDS" \
    --output-json "${OUT_DIR}/soak_gate_core.json" \
    | tee "${OUT_DIR}/soak_gate_core.log"
fi

echo "[run] snapshot + metrics capture"
curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/snapshot" > "${OUT_DIR}/system_snapshot.json"
curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/metrics?window_seconds=${WINDOW_SECONDS}" > "${OUT_DIR}/system_metrics.json"
curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/readyz" > "${OUT_DIR}/system_readyz.json"

cat > "${OUT_DIR}/run_meta.txt" <<EOF
timestamp=${TS}
base_url=${BASE_URL}
runtime_profile=strict
product_track=core
run_soak=${RUN_SOAK}
duration_hours=${DURATION_HOURS}
window_seconds=${WINDOW_SECONDS}
EOF

echo "[ok] core evidence bundle ready: ${OUT_DIR}"
