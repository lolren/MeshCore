# What Is Custom (MeshCore JSON Bridge)

This file maps the bridge-specific code so it is clear what was added.

## Architecture

Browser/UI -> `localhost:8865` (PC bridge) -> MeshCore serial protocol -> LoRa mesh.

## PC Webserver Custom Code

Primary files:

- `meshcore_json_bridge/pc_webserver/meshcore_json_bridge_web.py`
- `meshcore_json_bridge/pc_webserver/index.html`
- `meshcore_json_bridge/pc_webserver/run.sh`

What they do:

- Host a local web UI for chat, node config, and serial settings.
- Expose Meshtastic-like JSON routes (`/json/*`) plus UI aliases (`/api/*`).
- Translate JSON calls to MeshCore Companion Protocol frames over serial or TCP (`tcp://<ip>:5000`).
- Parse contacts/messages and keep local message history for polling.

## Firmware Side

No firmware source modifications were required in this repo for the bridge API.

- Firmware build/flash workflow is documented in `meshcore_json_bridge/firmware/README.md`.
- Helper scripts live in `side_by_side_setup/`.

## Why This Repo Still Looks Large

MeshCore firmware requires its full source tree. Bridge behavior is concentrated in the files listed above.
