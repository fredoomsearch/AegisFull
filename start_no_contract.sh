#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

export AEGIS_START_CONTRACT_MODE="${AEGIS_START_CONTRACT_MODE:-none}"

exec ./start_aegis.sh "$@"
