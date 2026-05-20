#!/usr/bin/env bash
set -euo pipefail

# Full-track strict evidence bundle runner.
# What it does:
# - Runs strict full-track verify/hard-contract/soak checks against a live host.
# - Archives machine-readable evidence under artifacts/release_evidence/<timestamp>/.
#
# Why it exists:
# - Step 7 requires host-level proof (browser+image strict + soak) before Full GO.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BASE_URL="${AEGIS_BASE_URL:-http://127.0.0.1:8000}"
DURATION_HOURS="${AEGIS_SOAK_HOURS:-72}"
OUT_ROOT="${AEGIS_EVIDENCE_DIR:-artifacts/release_evidence}"
WINDOW_SECONDS="${AEGIS_CONTRACT_WINDOW_SECONDS:-900}"
DOCTOR_TIMEOUT_SECONDS="${AEGIS_DOCTOR_TIMEOUT_SECONDS:-20}"
DOCTOR_ATTEMPTS="${AEGIS_DOCTOR_ATTEMPTS:-2}"
RUN_CRYPTO_TESTNET_REHEARSAL="${AEGIS_RUN_CRYPTO_TESTNET_REHEARSAL:-0}"
CRYPTO_REHEARSAL_SUBMIT="${AEGIS_CRYPTO_REHEARSAL_SUBMIT:-0}"
CRYPTO_REHEARSAL_SYMBOL="${AEGIS_CRYPTO_REHEARSAL_SYMBOL:-BTCUSDT}"
CRYPTO_REHEARSAL_SIDE="${AEGIS_CRYPTO_REHEARSAL_SIDE:-BUY}"
CRYPTO_REHEARSAL_QTY="${AEGIS_CRYPTO_REHEARSAL_QTY:-0.001}"
CRYPTO_REHEARSAL_HORIZON="${AEGIS_CRYPTO_REHEARSAL_HORIZON:-15}"
CRYPTO_REHEARSAL_REGIME="${AEGIS_CRYPTO_REHEARSAL_REGIME:-}"
SYNC_RELEASE_BOARD="${AEGIS_SYNC_RELEASE_BOARD:-0}"
SKIP_DOCTOR=0
PRECHECK_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --duration-hours)
      DURATION_HOURS="$2"
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
    --run-crypto-testnet-rehearsal)
      RUN_CRYPTO_TESTNET_REHEARSAL=1
      shift
      ;;
    --crypto-rehearsal-submit)
      CRYPTO_REHEARSAL_SUBMIT=1
      shift
      ;;
    --sync-release-board)
      SYNC_RELEASE_BOARD=1
      shift
      ;;
    --skip-doctor)
      SKIP_DOCTOR=1
      shift
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
export AEGIS_PRODUCT_TRACK=full

echo "[info] full strict evidence run"
echo "  base_url=${BASE_URL}"
echo "  duration_hours=${DURATION_HOURS}"
echo "  out_dir=${OUT_DIR}"
echo "  skip_doctor=${SKIP_DOCTOR}"
echo "  precheck_only=${PRECHECK_ONLY}"
echo "  doctor_timeout_seconds=${DOCTOR_TIMEOUT_SECONDS}"
echo "  doctor_attempts=${DOCTOR_ATTEMPTS}"
echo "  run_crypto_testnet_rehearsal=${RUN_CRYPTO_TESTNET_REHEARSAL}"
echo "  sync_release_board=${SYNC_RELEASE_BOARD}"

if [[ "$SKIP_DOCTOR" != "1" ]]; then
  echo "[run] doctor (full/fail-fast)"
  if ! "$PYTHON_BIN" -m app.scripts.doctor \
    --track full \
    --base-url "$BASE_URL" \
    --api-key "$API_KEY" \
    --timeout "$DOCTOR_TIMEOUT_SECONDS" \
    --attempts "$DOCTOR_ATTEMPTS" \
    --json \
    | tee "${OUT_DIR}/doctor_full.json"; then
    echo "[fail] full doctor precheck failed. Resolve full-track blockers first (browser runtime + image backend)." >&2
    if [[ -s "${OUT_DIR}/doctor_full.json" ]]; then
      echo "[detail] doctor blockers:" >&2
      "$PYTHON_BIN" - "${OUT_DIR}/doctor_full.json" <<'PY'
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
    echo "[hint] Re-run: python -m app.scripts.doctor --track full --base-url ${BASE_URL}" >&2
    exit 2
  fi
fi

echo "[run] image backend probe (full/fail-fast)"
IMAGE_PROBE_CMD=(
  "$PYTHON_BIN" -m app.scripts.image_backend_probe
  --endpoint "${AEGIS_IMAGE_ENDPOINT:-}"
  --require-checkpoint
  --json
)
if [[ -n "${AEGIS_IMAGE_PYTHON:-}" ]]; then
  IMAGE_PROBE_CMD+=(--python-bin "${AEGIS_IMAGE_PYTHON}")
fi
if [[ "${AEGIS_REQUIRE_NVIDIA_SMI:-0}" =~ ^(1|true|yes|on)$ ]]; then
  IMAGE_PROBE_CMD+=(--require-nvidia-smi)
fi
if [[ "${AEGIS_REQUIRE_IMAGE_TORCH_CUDA:-0}" =~ ^(1|true|yes|on)$ ]]; then
  IMAGE_PROBE_CMD+=(--require-torch-cuda)
fi
if ! "${IMAGE_PROBE_CMD[@]}" | tee "${OUT_DIR}/image_backend_probe.json"; then
  echo "[fail] image backend probe failed. Full strict requires a healthy backend with checkpoints." >&2
  echo "[hint] Re-run: python -m app.scripts.image_backend_probe --endpoint \"${AEGIS_IMAGE_ENDPOINT:-http://127.0.0.1:8188/prompt}\" --require-checkpoint" >&2
  echo "[hint] Optional deep check: export AEGIS_IMAGE_PYTHON=/path/to/comfyui/.venv/bin/python" >&2
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
product_track=full
mode=precheck-only
window_seconds=${WINDOW_SECONDS}
EOF
  echo "[ok] full precheck bundle ready: ${OUT_DIR}"
  exit 0
fi

echo "[run] verify_full (strict/full)"
"$PYTHON_BIN" -m app.scripts.verify_full \
  --runtime-profile strict \
  --product-track full \
  --strict-browser-smoke \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --files-api-key "$FILES_KEY" \
  | tee "${OUT_DIR}/verify_full.log"

echo "[run] hard_contract_check (strict)"
"$PYTHON_BIN" -m app.scripts.hard_contract_check \
  --strict \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --run-no-loop \
  --window-seconds "$WINDOW_SECONDS" \
  | tee "${OUT_DIR}/hard_contract.log"

echo "[run] soak_gate (${DURATION_HOURS}h)"
"$PYTHON_BIN" -m app.scripts.soak_gate \
  --base-url "$BASE_URL" \
  --api-key "$API_KEY" \
  --duration-hours "$DURATION_HOURS" \
  --window-seconds "$WINDOW_SECONDS" \
  --output-json "${OUT_DIR}/soak_gate.json" \
  | tee "${OUT_DIR}/soak_gate.log"

echo "[run] snapshot + metrics capture"
curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/snapshot" > "${OUT_DIR}/system_snapshot.json"
curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/metrics?window_seconds=${WINDOW_SECONDS}" > "${OUT_DIR}/system_metrics.json"
curl -fsS -H "X-API-Key: ${API_KEY}" "${BASE_URL}/system/readyz" > "${OUT_DIR}/system_readyz.json"

if [[ "$RUN_CRYPTO_TESTNET_REHEARSAL" == "1" ]]; then
  echo "[run] crypto_testnet_rehearsal"
  CRYPTO_REHEARSAL_CMD=(
    "$PYTHON_BIN" app/scripts/crypto_testnet_rehearsal.py
    --base-url "$BASE_URL"
    --api-key "$API_KEY"
    --files-api-key "$FILES_KEY"
    --symbol "$CRYPTO_REHEARSAL_SYMBOL"
    --side "$CRYPTO_REHEARSAL_SIDE"
    --quantity "$CRYPTO_REHEARSAL_QTY"
    --horizon-minutes "$CRYPTO_REHEARSAL_HORIZON"
    --execution-mode testnet
    --out-dir "${OUT_DIR}/crypto_testnet_rehearsal"
  )
  if [[ -n "$CRYPTO_REHEARSAL_REGIME" ]]; then
    CRYPTO_REHEARSAL_CMD+=(--regime "$CRYPTO_REHEARSAL_REGIME")
  fi
  if [[ "$CRYPTO_REHEARSAL_SUBMIT" == "1" ]]; then
    CRYPTO_REHEARSAL_CMD+=(--submit-if-allowed)
  fi
  "${CRYPTO_REHEARSAL_CMD[@]}" | tee "${OUT_DIR}/crypto_testnet_rehearsal.log"
fi

echo "[run] release evidence summary"
"$PYTHON_BIN" -m app.scripts.release_evidence_summary \
  --bundle-dir "${OUT_DIR}" \
  --json \
  | tee "${OUT_DIR}/release_summary.json"

if [[ "$SYNC_RELEASE_BOARD" == "1" ]]; then
  echo "[run] release_board_sync"
  "$PYTHON_BIN" -m app.scripts.release_board_sync \
    --board-path "${ROOT_DIR}/docs/release_board.md" \
    --evidence-root "${OUT_ROOT}"
fi

cat > "${OUT_DIR}/run_meta.txt" <<EOF
timestamp=${TS}
base_url=${BASE_URL}
runtime_profile=strict
product_track=full
duration_hours=${DURATION_HOURS}
window_seconds=${WINDOW_SECONDS}
run_crypto_testnet_rehearsal=${RUN_CRYPTO_TESTNET_REHEARSAL}
crypto_rehearsal_submit=${CRYPTO_REHEARSAL_SUBMIT}
sync_release_board=${SYNC_RELEASE_BOARD}
EOF

echo "[ok] evidence bundle ready: ${OUT_DIR}"
