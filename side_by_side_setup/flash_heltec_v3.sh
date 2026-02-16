#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./side_by_side_setup/flash_heltec_v3.sh <profile> <serial-port> --yes

Examples:
  ./side_by_side_setup/flash_heltec_v3.sh companion-usb /dev/ttyUSB1 --yes
  WIFI_SSID="MyWiFi" WIFI_PWD="Secret123" \
    ./side_by_side_setup/flash_heltec_v3.sh companion-wifi /dev/ttyUSB1 --yes
  WIFI_SSID="MyWiFi" WIFI_PWD="Secret123" WIFI_SSID_2="BackupWiFi" WIFI_PWD_2="BackupSecret" \
    ./side_by_side_setup/flash_heltec_v3.sh companion-wifi /dev/ttyUSB1 --yes
EOF
}

profile_to_env() {
  case "${1}" in
    companion-usb) echo "Heltec_v3_companion_radio_usb" ;;
    companion-ble) echo "Heltec_v3_companion_radio_ble" ;;
    companion-wifi) echo "Heltec_v3_companion_radio_wifi" ;;
    repeater) echo "Heltec_v3_repeater" ;;
    room-server) echo "Heltec_v3_room_server" ;;
    terminal-chat) echo "Heltec_v3_terminal_chat" ;;
    kiss-modem) echo "Heltec_v3_kiss_modem" ;;
    *) return 1 ;;
  esac
}

if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

PROFILE="${1:-}"
PORT="${2:-}"
CONFIRM="${3:-}"

if [[ -z "${PROFILE}" || -z "${PORT}" ]]; then
  usage >&2
  exit 1
fi

if ! ENV_NAME="$(profile_to_env "${PROFILE}")"; then
  echo "Unknown profile: ${PROFILE}" >&2
  usage >&2
  exit 1
fi

if [[ "${CONFIRM}" != "--yes" ]]; then
  echo "Refusing to flash without explicit confirmation."
  echo "Re-run with --yes when your target board is connected."
  exit 2
fi

if [[ ! -e "${PORT}" ]]; then
  echo "Serial port not found: ${PORT}" >&2
  exit 1
fi

echo "Building before flash..."
"${SCRIPT_DIR}/build_heltec_v3.sh" "${PROFILE}"

if [[ -n "${PIO_BIN:-}" ]]; then
  PIO="${PIO_BIN}"
elif [[ -x "${REPO_ROOT}/.venv/bin/pio" ]]; then
  PIO="${REPO_ROOT}/.venv/bin/pio"
elif [[ -x "/home/lolren/Desktop/Meshtastic-json/firmware/.venv/bin/pio" ]]; then
  PIO="/home/lolren/Desktop/Meshtastic-json/firmware/.venv/bin/pio"
else
  PIO="$(command -v pio)"
fi

UPLOAD_FLAGS="${PLATFORMIO_BUILD_FLAGS:-}"
if [[ "${PROFILE}" == "companion-wifi" ]]; then
  if [[ -n "${WIFI_SSID:-}${WIFI_PWD:-}${WIFI_SSID_2:-}${WIFI_PWD_2:-}${WIFI_SSID_3:-}${WIFI_PWD_3:-}" ]]; then
    if [[ -z "${WIFI_SSID:-}" || -z "${WIFI_PWD:-}" ]]; then
      echo "companion-wifi: WIFI_SSID and WIFI_PWD (primary AP) must be set together." >&2
      exit 1
    fi

    if [[ -n "${WIFI_SSID_2:-}" || -n "${WIFI_PWD_2:-}" ]]; then
      if [[ -z "${WIFI_SSID_2:-}" || -z "${WIFI_PWD_2:-}" ]]; then
        echo "companion-wifi: WIFI_SSID_2 and WIFI_PWD_2 must be set together." >&2
        exit 1
      fi
    fi

    if [[ -n "${WIFI_SSID_3:-}" || -n "${WIFI_PWD_3:-}" ]]; then
      if [[ -z "${WIFI_SSID_3:-}" || -z "${WIFI_PWD_3:-}" ]]; then
        echo "companion-wifi: WIFI_SSID_3 and WIFI_PWD_3 must be set together." >&2
        exit 1
      fi
    fi

    # Ensure upload rebuild (if triggered) uses explicit credentials, not board defaults.
    UPLOAD_FLAGS="${UPLOAD_FLAGS} -DWIFI_SSID='\"${WIFI_SSID}\"' -DWIFI_PWD='\"${WIFI_PWD}\"'"
    if [[ -n "${WIFI_SSID_2:-}" ]]; then
      UPLOAD_FLAGS="${UPLOAD_FLAGS} -DWIFI_SSID_2='\"${WIFI_SSID_2}\"' -DWIFI_PWD_2='\"${WIFI_PWD_2}\"'"
    fi
    if [[ -n "${WIFI_SSID_3:-}" ]]; then
      UPLOAD_FLAGS="${UPLOAD_FLAGS} -DWIFI_SSID_3='\"${WIFI_SSID_3}\"' -DWIFI_PWD_3='\"${WIFI_PWD_3}\"'"
    fi
  fi
fi

echo "Flashing ${PROFILE} (${ENV_NAME}) to ${PORT}"
cd "${REPO_ROOT}"
FIRMWARE_VERSION="${FIRMWARE_VERSION:-local-dev}" \
DISABLE_DEBUG="${DISABLE_DEBUG:-1}" \
PLATFORMIO_BUILD_FLAGS="${UPLOAD_FLAGS}" \
  "${PIO}" run -e "${ENV_NAME}" -t upload --upload-port "${PORT}"

echo "Flash complete."
