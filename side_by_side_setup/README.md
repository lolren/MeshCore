# MeshCore Heltec V3 Side-By-Side

This folder provides a simple workflow for building and flashing a second Heltec V3 with MeshCore while keeping your LongFast node separate.

## Folder Separation

- Meshtastic/LongFast repo: `/home/lolren/Desktop/Meshtastic-json/firmware`
- MeshCore repo: `/home/lolren/Desktop/MeshCore-sideby/meshcore`

Keep changes isolated in their own repo/folder to avoid mixing firmware and bridge code across stacks.

## Profiles

- `companion-usb` -> `Heltec_v3_companion_radio_usb`
- `companion-ble` -> `Heltec_v3_companion_radio_ble`
- `companion-wifi` -> `Heltec_v3_companion_radio_wifi`
- `repeater` -> `Heltec_v3_repeater`
- `room-server` -> `Heltec_v3_room_server`
- `terminal-chat` -> `Heltec_v3_terminal_chat`
- `kiss-modem` -> `Heltec_v3_kiss_modem`

## Build Only (Safe)

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/build_heltec_v3.sh companion-usb
```

The script only compiles firmware and never flashes.

## Flash Later (When Board Is Ready)

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/flash_heltec_v3.sh companion-usb /dev/ttyUSB1 --yes
```

Flash requires `--yes` so it cannot run by accident.

## WiFi Companion Build

`companion-wifi` can use your credentials at build time:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
WIFI_SSID="YourSSID" WIFI_PWD="YourPassword" \
  ./side_by_side_setup/build_heltec_v3.sh companion-wifi
```

Optional fallback APs (auto-try in order):

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
WIFI_SSID="PrimarySSID" WIFI_PWD="PrimaryPass" \
WIFI_SSID_2="BackupSSID" WIFI_PWD_2="BackupPass" \
./side_by_side_setup/build_heltec_v3.sh companion-wifi
```

Then flash that same profile when ready.

Quick one-command reflash with new Wi-Fi credentials:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/flash_wifi_heltec_v3.sh "YourSSID" 'YourPassword' /dev/ttyUSB0 --yes
```

That is all you need to change SSID/password later (re-run with new values).

One-command flash with fallback AP:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/flash_wifi_heltec_v3.sh \
  "PRIMARY_SSID" 'PRIMARY_PASSWORD' /dev/ttyUSB0 --yes \
  "BACKUP_SSID" 'BACKUP_PASSWORD'
```

After flash, watch serial to confirm network join and IP:

```bash
python3 - <<'PY'
import serial, time
s = serial.Serial('/dev/ttyUSB0', 115200, timeout=0.2)
end = time.time() + 20
while time.time() < end:
    data = s.read(4096)
    if data:
        print(data.decode('utf-8', errors='ignore'), end='')
s.close()
PY
```

Expected lines include:

- `[meshcore] WiFi companion mode`
- `[meshcore] AP[1] SSID: <your-primary-ssid>`
- `[meshcore] AP[2] SSID: <your-fallback-ssid>` (if set)
- `[meshcore] WiFi connected to '<joined-ssid>', IP=<ip> RSSI=<dbm>`
- `[meshcore] TCP server listening on 5000`

If you see `status=1`, the board cannot see that SSID (usually wrong name/case or 5GHz-only AP; ESP32 needs 2.4GHz).

## Running Side-By-Side

- LongFast node + local UI: `http://127.0.0.1:8765`
- MeshCore local JSON bridge + UI: `http://127.0.0.1:8865`
- MeshCore companion clients:
  - Web: `https://app.meshcore.nz`
  - USB/serial config for server modes: `https://config.meshcore.dev`

Start MeshCore local bridge:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./meshcore_json_bridge/pc_webserver/run.sh /dev/ttyUSB0
# or over Wi-Fi TCP:
./meshcore_json_bridge/pc_webserver/run.sh tcp://<meshcore-ip>:5000
```

## Notes

- MeshCore and LongFast/Meshtastic do not interoperate with each other.
- Keep each device on legal region settings for your location.
