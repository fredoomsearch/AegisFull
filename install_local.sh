#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

TRACK="${AEGIS_PRODUCT_TRACK:-core}"
if [[ "${1:-}" == "--track" && -n "${2:-}" ]]; then
  TRACK="$2"
  shift 2
fi
if [[ "$TRACK" != "core" && "$TRACK" != "full" ]]; then
  echo "[error] Invalid track '$TRACK'. Use core or full." >&2
  exit 2
fi

if [[ ! -d "venv" ]]; then
  python3 -m venv venv
fi

# shellcheck disable=SC1091
source "venv/bin/activate"
python -m pip install --upgrade pip >/dev/null
if [[ -f "requirements.txt" ]]; then
  python -m pip install -r requirements.txt
elif [[ -f "pyproject.toml" ]]; then
  python -m pip install -e .
else
  echo "[error] Missing requirements.txt and pyproject.toml; cannot install dependencies." >&2
  exit 2
fi

if [[ ! -f ".env" ]]; then
  cp .env.production.example .env 2>/dev/null || cp .env.demo.example .env
fi

python - <<'PY'
import secrets
from pathlib import Path

env_path = Path(".env")
text = env_path.read_text(encoding="utf-8")
replacements = {
    "aegis-demo-key-2026-strong": secrets.token_urlsafe(32),
    "set-a-different-strong-key": secrets.token_urlsafe(32),
}
for old, new in replacements.items():
    text = text.replace(old, new)
if "AEGIS_PRODUCT_TRACK=" not in text:
    text += "\nAEGIS_PRODUCT_TRACK=core\n"
if "AEGIS_RUNTIME_PROFILE=" not in text:
    text += "AEGIS_RUNTIME_PROFILE=strict\n"
env_path.write_text(text, encoding="utf-8")
PY

set -a
# shellcheck disable=SC1091
source ".env"
set +a

export AEGIS_PRODUCT_TRACK="$TRACK"

echo "[check] doctor (${TRACK})"
python -m app.scripts.doctor --track "$TRACK"

cat <<EOF
[ok] install_local completed
next:
  1) ./start_aegis.sh
  2) python -m app.scripts.doctor --track $TRACK --base-url http://127.0.0.1:8000
EOF
