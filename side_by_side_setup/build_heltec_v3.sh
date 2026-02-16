#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./side_by_side_setup/build_heltec_v3.sh <profile>

Profiles:
  companion-usb
  companion-ble
  companion-wifi
  repeater
  room-server
  terminal-chat
  kiss-modem

Env vars:
  PIO_BIN        Optional explicit path to pio binary.
  FIRMWARE_VERSION  Optional version string (default: local-dev).
  DISABLE_DEBUG  Optional, default 1.
  WIFI_SSID      Primary Wi-Fi SSID for companion-wifi profile.
  WIFI_PWD       Primary Wi-Fi password for companion-wifi profile.
  WIFI_SSID_2    Optional fallback Wi-Fi SSID.
  WIFI_PWD_2     Optional fallback Wi-Fi password.
  WIFI_SSID_3    Optional fallback Wi-Fi SSID.
  WIFI_PWD_3     Optional fallback Wi-Fi password.
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

resolve_pio() {
  if [[ -n "${PIO_BIN:-}" && -x "${PIO_BIN}" ]]; then
    echo "${PIO_BIN}"
    return
  fi

  if [[ -x "${REPO_ROOT}/.venv/bin/pio" ]]; then
    echo "${REPO_ROOT}/.venv/bin/pio"
    return
  fi

  # Reuse PlatformIO from the existing LongFast firmware workspace if present.
  if [[ -x "/home/lolren/Desktop/Meshtastic-json/firmware/.venv/bin/pio" ]]; then
    echo "/home/lolren/Desktop/Meshtastic-json/firmware/.venv/bin/pio"
    return
  fi

  if command -v pio >/dev/null 2>&1; then
    command -v pio
    return
  fi

  echo "No usable pio binary found. Set PIO_BIN=/path/to/pio" >&2
  exit 1
}

if [[ "${1:-}" == "" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

PROFILE="${1}"
if ! ENV_NAME="$(profile_to_env "${PROFILE}")"; then
  echo "Unknown profile: ${PROFILE}" >&2
  usage >&2
  exit 1
fi

PIO_BIN="$(resolve_pio)"
FIRMWARE_VERSION="${FIRMWARE_VERSION:-local-dev}"
DISABLE_DEBUG="${DISABLE_DEBUG:-1}"

EXTRA_FLAGS="${PLATFORMIO_BUILD_FLAGS:-}"
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

    EXTRA_FLAGS="${EXTRA_FLAGS} -DWIFI_SSID='\"${WIFI_SSID}\"' -DWIFI_PWD='\"${WIFI_PWD}\"'"
    if [[ -n "${WIFI_SSID_2:-}" ]]; then
      EXTRA_FLAGS="${EXTRA_FLAGS} -DWIFI_SSID_2='\"${WIFI_SSID_2}\"' -DWIFI_PWD_2='\"${WIFI_PWD_2}\"'"
    fi
    if [[ -n "${WIFI_SSID_3:-}" ]]; then
      EXTRA_FLAGS="${EXTRA_FLAGS} -DWIFI_SSID_3='\"${WIFI_SSID_3}\"' -DWIFI_PWD_3='\"${WIFI_PWD_3}\"'"
    fi
    echo "companion-wifi: overriding WIFI_SSID/WIFI_PWD from environment."
  else
    echo "companion-wifi: WIFI_SSID/WIFI_PWD not set; using defaults from variants/heltec_v3/platformio.ini"
  fi
fi

echo "Building MeshCore profile '${PROFILE}' (${ENV_NAME})"
echo "Using pio: ${PIO_BIN}"

cd "${REPO_ROOT}"
FIRMWARE_VERSION="${FIRMWARE_VERSION}" \
DISABLE_DEBUG="${DISABLE_DEBUG}" \
PLATFORMIO_BUILD_FLAGS="${EXTRA_FLAGS}" \
  "${PIO_BIN}" run -e "${ENV_NAME}"

echo ""
echo "Build complete:"
echo "  .pio/build/${ENV_NAME}/firmware.bin"
