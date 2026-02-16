# MeshCore JSON Bridge API Endpoints

Base URL (default):

- `http://127.0.0.1:8865`

The local bridge exposes:

- UI path: `/`
- UI-friendly API: `/api/*`
- Meshtastic-like aliases: `/json/*`

## Endpoint Matrix

| Method | Path | Alias | Purpose |
|---|---|---|---|
| `GET` | `/` | n/a | Serve local web UI (`index.html`) |
| `GET` | `/api/config` | n/a | Read current bridge target/transport config |
| `POST` | `/api/config` | n/a | Update bridge target/transport config |
| `GET` | `/api/report` | `/json/report` | Device + owner + radio summary |
| `GET` | `/api/node-config` | `/json/config/node` | Read node owner config |
| `POST` | `/api/node-config` | `/json/config/node` | Update node owner config |
| `GET` | `/api/nodes` | `/json/nodes` | Return known nodes/contacts |
| `GET` | `/api/messages` | `/json/chat/messages` | Poll message history |
| `POST` | `/api/send` | `/json/chat/send` | Send channel or private text |
| `OPTIONS` | `/api/*`, `/json/*` | n/a | CORS preflight |

## `GET /api/config`

Returns the currently active bridge transport.

Example response:

```json
{
  "status": "ok",
  "serial_port": "tcp://192.168.1.148:5000",
  "baud": 115200,
  "connected": true,
  "transport": "tcp",
  "target": "tcp://192.168.1.148:5000",
  "esp_base_url": "tcp://192.168.1.148:5000",
  "tcp_host": "192.168.1.148",
  "tcp_port": 5000
}
```

## `POST /api/config`

Set target and reconnect immediately.

Request JSON:

- `serial_port` (string, required): bridge target
- `baud` (int, optional): serial baud, default current value

Accepted `serial_port` formats:

- Serial: `/dev/ttyUSB0`, `serial:///dev/ttyUSB0`, `COM5`
- TCP: `tcp://192.168.1.148:5000`, `192.168.1.148:5000`, `meshcore.local:5000`

Example:

```bash
curl -sS -X POST http://127.0.0.1:8865/api/config \
  -H "Content-Type: application/json" \
  -d '{"serial_port":"tcp://192.168.1.148:5000","baud":115200}'
```

## `GET /api/report` (`/json/report`)

Returns summary data used by dashboards.

Response fields:

- `data.device`: model/version/build
- `data.owner`: id + long/short name
- `data.radio`: freq/bw/sf/cr/tx power
- `data.meshcore`: protocol and limits

## `GET /api/node-config` (`/json/config/node`)

Returns owner fields currently writable by bridge:

- `data.owner.id`
- `data.owner.long_name`
- `data.owner.short_name`

Current Wi-Fi block is informational placeholder in bridge response.

## `POST /api/node-config` (`/json/config/node`)

Updates owner name only (MeshCore companion command `CMD_SET_ADVERT_NAME`).

Request JSON:

- `longName` (string, optional)
- `shortName` (string, optional; used if `longName` missing)
- `reboot` (bool, optional; accepted but not used by companion command)

Example:

```bash
curl -sS -X POST http://127.0.0.1:8865/api/node-config \
  -H "Content-Type: application/json" \
  -d '{"longName":"STROUD_BOT","shortName":"STRO","reboot":false}'
```

## `GET /api/nodes` (`/json/nodes`)

Returns self node plus known contacts.

Query params are currently ignored by backend, but accepted by route.

Example:

```bash
curl -sS "http://127.0.0.1:8865/api/nodes?limit=50"
```

## `GET /api/messages` (`/json/chat/messages`)

Polls history pulled from MeshCore companion message sync.

Query parameters:

- `limit` (1..100, default `30`)
- `since` (unix timestamp, optional)
- `peer` (`!hex12`, `mc:<hex>`, raw hex, or contact name)
- `channel` (`0..7`, optional)
- `includeBroadcast` (`true|false`, default `true`)
- `includeDm` (`true|false`, default `true`)

Example:

```bash
curl -sS "http://127.0.0.1:8865/api/messages?limit=20&includeBroadcast=true&includeDm=true"
```

Message object fields:

- `timestamp`, `is_boot_relative`
- `channel`
- `scope` (`channel` or `private`)
- `direction` (`in` or `out`)
- `sender_id`, `to_id`, `peer_id`
- `text`

## `POST /api/send` (`/json/chat/send`)

Send channel or private text.

Request JSON:

- `text` (string, required, max 140 bytes UTF-8)
- `channel` (int `0..7`, optional, default `0`) for channel send
- `to` (string, optional) for private send

Rules:

- If `to` is set (and not broadcast), bridge sends private message.
- Otherwise, bridge sends channel message on `channel`.

Examples:

```bash
# Channel message
curl -sS -X POST http://127.0.0.1:8865/api/send \
  -H "Content-Type: application/json" \
  -d '{"text":"hello meshcore","channel":0}'

# Private message
curl -sS -X POST http://127.0.0.1:8865/api/send \
  -H "Content-Type: application/json" \
  -d '{"text":"private ping","to":"!856dd29cf14e"}'
```

## Error Model

Common envelope:

```json
{"status":"error","error":"<code>","detail":"optional"}
```

Common `error` values:

- Request parsing: `invalid_content_length`, `missing_body`, `body_too_large`, `invalid_json`, `json_object_required`
- Config: `field_serial_port_required`, `field_serial_port_invalid`, `invalid_serial_config`
- Reachability: `meshcore_unreachable`
- Domain validation (400 on mutable APIs): `field_text_required`, `text_too_long`, `field_peer_invalid`, `field_to_invalid`, `field_to_not_found`, `send_channel_failed`, `send_private_failed`

