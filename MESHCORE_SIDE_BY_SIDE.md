# MeshCore Side-By-Side Setup

This repo is cloned separately at:

- `/home/lolren/Desktop/MeshCore-sideby/meshcore`

Use this guide to prepare a second Heltec V3 running MeshCore while your LongFast node keeps running.

## Start Here

- Side-by-side scripts and guide: `side_by_side_setup/README.md`
- MeshCore JSON bridge layout + run guide: `meshcore_json_bridge/README.md`

## Quick Commands

Build only (no flash):

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/build_heltec_v3.sh companion-usb
```

Flash later when your second board is connected:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./side_by_side_setup/flash_heltec_v3.sh companion-usb /dev/ttyUSB1 --yes
```

## Important

- MeshCore and LongFast/Meshtastic are separate ecosystems and do not interoperate.
- They can run next to each other on separate devices.
