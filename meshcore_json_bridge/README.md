# MeshCore JSON Bridge

This project adds a Meshtastic-like JSON API for MeshCore by running a local PC bridge.

Structure:

- `pc_webserver/` -> Python bridge + browser UI.
- `firmware/` -> firmware/flash notes for Heltec V3.
- `API_ENDPOINTS.md` -> complete route reference with request/response examples.

Workspace separation:

- MeshCore custom repo: `/home/lolren/Desktop/MeshCore-sideby/meshcore`
- Meshtastic/LongFast custom repo: `/home/lolren/Desktop/Meshtastic-json/firmware`

This is intentionally not tied to Meshtastic internals. The bridge talks MeshCore Companion Protocol over serial and exposes stable JSON routes.

## Quick Start

1. Flash MeshCore on Heltec V3 (see `firmware/README.md`).
2. Start the local bridge:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./meshcore_json_bridge/pc_webserver/run.sh /dev/ttyUSB0
```

For MeshCore over Wi-Fi transport:

```bash
cd /home/lolren/Desktop/MeshCore-sideby/meshcore
./meshcore_json_bridge/pc_webserver/run.sh tcp://<meshcore-ip>:5000
```

3. Open the UI:

- `http://127.0.0.1:8865`

If you need browser access from another device, bind on all interfaces:

```bash
HOST=0.0.0.0 PORT=8865 ./meshcore_json_bridge/pc_webserver/run.sh /dev/ttyUSB0
```

Then open `http://<your-pc-ip>:8865` from LAN.

## Exposed Endpoints

- `GET /json/report` and `GET /api/report`
- `GET /json/nodes` and `GET /api/nodes`
- `GET /json/chat/messages` and `GET /api/messages`
- `POST /json/chat/send` and `POST /api/send`
- `GET/POST /json/config/node` and `GET/POST /api/node-config`
- `GET/POST /api/config` (serial bridge config)

Full endpoint documentation:

- `meshcore_json_bridge/API_ENDPOINTS.md`

`/api/config` target accepts both:

- serial: `/dev/ttyUSB0`, `serial:///dev/ttyUSB0`
- TCP: `192.168.1.50:5000`, `tcp://192.168.1.50:5000`

## ID Format

- Bridge responses use node IDs as `!<12-hex>` (MeshCore public-key prefix).
- Input accepts `!<hex>`, `mc:<hex>`, raw hex, or contact name.

## Custom Code Map

See `meshcore_json_bridge/WHAT_IS_CUSTOM.md` for file-level details.
