#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./side_by_side_setup/flash_wifi_heltec_v3.sh <ssid1> <password1> <serial-port> --yes [ssid2 password2] [ssid3 password3]

Example:
  ./side_by_side_setup/flash_wifi_heltec_v3.sh PRIMARY_SSID 'PRIMARY_PASSWORD' /dev/ttyUSB0 --yes
  ./side_by_side_setup/flash_wifi_heltec_v3.sh PRIMARY_SSID 'PRIMARY_PASSWORD' /dev/ttyUSB0 --yes BACKUP_SSID 'BACKUP_PASSWORD'
EOF
}

SSID="${1:-}"
PASSWORD="${2:-}"
PORT="${3:-}"
CONFIRM="${4:-}"
SSID_2="${5:-}"
PASSWORD_2="${6:-}"
SSID_3="${7:-}"
PASSWORD_3="${8:-}"

if [[ -z "${SSID}" || -z "${PASSWORD}" || -z "${PORT}" || -z "${CONFIRM}" ]]; then
  usage >&2
  exit 1
fi

if [[ "$#" -ne 4 && "$#" -ne 6 && "$#" -ne 8 ]]; then
  usage >&2
  exit 1
fi

if [[ "${CONFIRM}" != "--yes" ]]; then
  echo "Refusing to flash without explicit confirmation (--yes)." >&2
  exit 2
fi

if [[ "$#" -eq 8 ]]; then
  WIFI_SSID="${SSID}" WIFI_PWD="${PASSWORD}" \
  WIFI_SSID_2="${SSID_2}" WIFI_PWD_2="${PASSWORD_2}" \
  WIFI_SSID_3="${SSID_3}" WIFI_PWD_3="${PASSWORD_3}" \
    "${SCRIPT_DIR}/flash_heltec_v3.sh" companion-wifi "${PORT}" --yes
elif [[ "$#" -eq 6 ]]; then
  WIFI_SSID="${SSID}" WIFI_PWD="${PASSWORD}" \
  WIFI_SSID_2="${SSID_2}" WIFI_PWD_2="${PASSWORD_2}" \
    "${SCRIPT_DIR}/flash_heltec_v3.sh" companion-wifi "${PORT}" --yes
else
  WIFI_SSID="${SSID}" WIFI_PWD="${PASSWORD}" \
    "${SCRIPT_DIR}/flash_heltec_v3.sh" companion-wifi "${PORT}" --yes
fi
