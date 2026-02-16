# Firmware Side (MeshCore JSON Bridge)

The JSON endpoints are implemented on the PC bridge layer, not inside firmware HTTP handlers.

Firmware on the Heltec V3 still needs a compatible MeshCore profile (for serial companion protocol).

## Recommended Profile

- `companion-usb` (`Heltec_v3_companion_radio_usb`)

## Build Only

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/build_heltec_v3.sh companion-usb
```

## Flash (explicit confirm)

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/flash_heltec_v3.sh companion-usb /dev/ttyUSB0 --yes
```

## Other Profiles

See `side_by_side_setup/README.md` for:

- `companion-ble`
- `companion-wifi`
- `repeater`
- `room-server`
- `terminal-chat`
- `kiss-modem`

For Wi-Fi bridge target, flash `companion-wifi` with build-time credentials:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
WIFI_SSID="YourSSID" WIFI_PWD="YourPassword" \
  ./side_by_side_setup/flash_heltec_v3.sh companion-wifi /dev/ttyUSB0 --yes
```

## Verify Serial Link

After flash, test the bridge API from the PC server:

```bash
curl -sS http://127.0.0.1:8865/api/report
curl -sS http://127.0.0.1:8865/api/nodes
curl -sS "http://127.0.0.1:8865/api/messages?limit=5"
```
