#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-/dev/ttyUSB0}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8865}"
BAUD="${BAUD:-115200}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "${SCRIPT_DIR}/meshcore_json_bridge_web.py" \
  --host "${HOST}" \
  --port "${PORT}" \
  --target "${TARGET}" \
  --baud "${BAUD}"
