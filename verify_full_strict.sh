#!/usr/bin/env bash
set -euo pipefail

# Strict extended verification:
# - identical to ./verify_full.sh
# - BUT fails if browser runtime is unavailable (requires headless Chromium/Brave working)
#
# Usage:
#   ./start_aegis.sh
#   ./verify_full_strict.sh --base-url http://127.0.0.1:8000

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

exec ./verify_full.sh --product-track full --strict-browser-smoke "$@"
