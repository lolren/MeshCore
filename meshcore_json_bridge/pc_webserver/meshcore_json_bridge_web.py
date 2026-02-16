#!/usr/bin/env python3
"""MeshCore JSON Bridge.

Exposes Meshtastic-like JSON endpoints over a local HTTP server by speaking
MeshCore Companion Protocol over serial.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import parse

import serial

MAX_REQUEST_BODY = 8192
MAX_HISTORY = 2000
MAX_MESSAGE_TEXT = 140
INDEX_HTML = Path(__file__).with_name("index.html")

APP_PROTOCOL_VERSION = 3

# Command codes
CMD_APP_START = 1
CMD_SEND_TXT_MSG = 2
CMD_SEND_CHANNEL_TXT_MSG = 3
CMD_GET_CONTACTS = 4
CMD_SET_ADVERT_NAME = 8
CMD_SYNC_NEXT_MESSAGE = 10
CMD_DEVICE_QUERY = 22

# Response codes
RESP_OK = 0
RESP_ERR = 1
RESP_CONTACTS_START = 2
RESP_CONTACT = 3
RESP_END_OF_CONTACTS = 4
RESP_SELF_INFO = 5
RESP_SENT = 6
RESP_CONTACT_MSG_RECV = 7
RESP_CHANNEL_MSG_RECV = 8
RESP_NO_MORE_MESSAGES = 10
RESP_DEVICE_INFO = 13
RESP_CONTACT_MSG_RECV_V3 = 16
RESP_CHANNEL_MSG_RECV_V3 = 17

# Push codes
PUSH_CODE_MSG_WAITING = 0x83

TXT_TYPE_PLAIN = 0
TXT_TYPE_SIGNED_PLAIN = 2

BROADCAST_ID = "!ffffffff"


def _cstr(raw: bytes) -> str:
    i = raw.find(b"\x00")
    if i >= 0:
        raw = raw[:i]
    return raw.decode("utf-8", errors="replace").strip()


def _parse_int(value: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and out < minimum:
        out = minimum
    if maximum is not None and out > maximum:
        out = maximum
    return out


def _parse_bool(value: Any | None, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return default
    v = str(value).strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


def _id_from_prefix(prefix6: bytes) -> str:
    return f"!{prefix6.hex()}"


def _trim_name(name: str, max_len: int = 31) -> str:
    return name.strip()[:max_len]


def _normalize_serial_port(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("serial_port_required")

    if value.startswith("serial://"):
        value = value[len("serial://") :]
    elif value.startswith("file://"):
        value = value[len("file://") :]

    low = value.lower()
    if low.startswith("http://") or low.startswith("https://"):
        raise ValueError("meshcore_bridge_uses_serial_not_ip")

    if re.fullmatch(r"com\d+", value, flags=re.IGNORECASE):
        return value.upper()
    if value.startswith("/dev/"):
        return value
    if re.fullmatch(r"tty[A-Za-z0-9._-]+", value):
        return f"/dev/{value}"
    if re.fullmatch(r"cu\.[A-Za-z0-9._-]+", value):
        return f"/dev/{value}"
    if "/" in value:
        return value

    raise ValueError("serial_port_format_invalid")


def _parse_target(raw: str, baud: int) -> dict[str, Any]:
    value = raw.strip()
    if not value:
        raise ValueError("target_required")

    low = value.lower()
    if low.startswith("serial://"):
        serial_port = _normalize_serial_port(value[len("serial://") :])
        return {"transport": "serial", "serial_port": serial_port, "baud": int(baud)}
    if low.startswith("file://"):
        serial_port = _normalize_serial_port(value[len("file://") :])
        return {"transport": "serial", "serial_port": serial_port, "baud": int(baud)}
    if low.startswith("tcp://"):
        parsed = parse.urlsplit(value)
        host = parsed.hostname
        if not host:
            raise ValueError("tcp_target_missing_host")
        port = int(parsed.port or 5000)
        return {"transport": "tcp", "host": host, "port": port}
    if low.startswith("http://") or low.startswith("https://"):
        parsed = parse.urlsplit(value)
        host = parsed.hostname
        if not host:
            raise ValueError("tcp_target_missing_host")
        port = int(parsed.port or 5000)
        return {"transport": "tcp", "host": host, "port": port}

    # Serial aliases.
    if re.fullmatch(r"com\d+", value, flags=re.IGNORECASE):
        serial_port = _normalize_serial_port(value)
        return {"transport": "serial", "serial_port": serial_port, "baud": int(baud)}
    if value.startswith("/dev/"):
        serial_port = _normalize_serial_port(value)
        return {"transport": "serial", "serial_port": serial_port, "baud": int(baud)}
    if re.fullmatch(r"tty[A-Za-z0-9._-]+", value):
        serial_port = _normalize_serial_port(value)
        return {"transport": "serial", "serial_port": serial_port, "baud": int(baud)}
    if re.fullmatch(r"cu\.[A-Za-z0-9._-]+", value):
        serial_port = _normalize_serial_port(value)
        return {"transport": "serial", "serial_port": serial_port, "baud": int(baud)}

    # TCP host:port.
    if ":" in value and "/" not in value:
        host, port_raw = value.rsplit(":", 1)
        host = host.strip()
        if host and port_raw.isdigit():
            return {"transport": "tcp", "host": host, "port": int(port_raw)}

    # TCP host without explicit port.
    if re.fullmatch(r"[A-Za-z0-9._-]+", value):
        return {"transport": "tcp", "host": value, "port": 5000}

    raise ValueError("target_format_invalid")


def _target_string(spec: dict[str, Any]) -> str:
    if spec.get("transport") == "serial":
        return str(spec.get("serial_port", ""))
    return f"tcp://{spec.get('host')}:{int(spec.get('port', 5000))}"


class MeshCoreClient:
    def __init__(self, serial_port: str, baud: int) -> None:
        self.baud = int(baud)
        self._target = _parse_target(serial_port, self.baud)
        self.serial_port = _target_string(self._target)

        self._lock = threading.RLock()
        self._ser: serial.Serial | None = None
        self._sock: socket.socket | None = None
        self._ready = False

        self._contacts_by_id: dict[str, dict[str, Any]] = {}
        self._device_info: dict[str, Any] = {}
        self._self_info: dict[str, Any] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def set_serial(self, serial_port: str, baud: int) -> None:
        with self._lock:
            baud = int(baud)
            parsed = _parse_target(serial_port, baud)
            normalized_target = _target_string(parsed)
            changed = normalized_target != self.serial_port or baud != self.baud
            self._target = parsed
            self.serial_port = normalized_target
            self.baud = baud
            if changed:
                self._close_locked(clear_state=False)

    def get_config(self) -> dict[str, Any]:
        with self._lock:
            transport = str(self._target.get("transport", "serial"))
            connected = False
            if transport == "serial":
                connected = bool(self._ser and self._ser.is_open and self._ready)
            else:
                connected = bool(self._sock and self._ready)

            out: dict[str, Any] = {
                "serial_port": self.serial_port,
                "baud": self.baud,
                "connected": connected,
                "transport": transport,
                "target": self.serial_port,
            }
            if transport == "serial":
                out["esp_base_url"] = f"serial://{self.serial_port}"
            else:
                host = str(self._target.get("host", ""))
                port = int(self._target.get("port", 5000))
                out["esp_base_url"] = f"tcp://{host}:{port}"
                out["tcp_host"] = host
                out["tcp_port"] = port

            return out

    def get_report(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_ready_locked()

            owner_name = self._self_info.get("node_name", "MeshCore Node")
            owner_id = self._self_id_locked()
            short_name = owner_name[:4] if owner_name else "MC"

            return {
                "status": "ok",
                "data": {
                    "device": {
                        "hw_model": self._device_info.get("manufacturer", "MeshCore"),
                        "firmware_version": self._device_info.get("firmware_version", ""),
                        "build_date": self._device_info.get("build_date", ""),
                        "reboot_counter": None,
                    },
                    "owner": {
                        "id": owner_id,
                        "long_name": owner_name,
                        "short_name": short_name,
                    },
                    "wifi": {
                        "ip": None,
                        "rssi": None,
                    },
                    "radio": {
                        "freq_mhz": self._self_info.get("freq_mhz"),
                        "bw_khz": self._self_info.get("bw_khz"),
                        "sf": self._self_info.get("sf"),
                        "cr": self._self_info.get("cr"),
                        "tx_power_dbm": self._self_info.get("tx_power_dbm"),
                    },
                    "meshcore": {
                        "protocol_version": APP_PROTOCOL_VERSION,
                        "max_contacts": self._device_info.get("max_contacts"),
                        "max_channels": self._device_info.get("max_channels"),
                    },
                },
            }

    def get_node_config(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_ready_locked()
            owner_name = self._self_info.get("node_name", "MeshCore Node")
            short_name = owner_name[:4] if owner_name else "MC"
            return {
                "status": "ok",
                "data": {
                    "owner": {
                        "id": self._self_id_locked(),
                        "long_name": owner_name,
                        "short_name": short_name,
                        "node_num": 0,
                    },
                    "wifi": {
                        "enabled": False,
                        "ssid": "",
                        "psk_set": False,
                    },
                },
            }

    def set_node_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_ready_locked()

            long_name = payload.get("longName")
            short_name = payload.get("shortName")

            desired_name = ""
            if isinstance(long_name, str) and long_name.strip():
                desired_name = _trim_name(long_name)
            elif isinstance(short_name, str) and short_name.strip():
                desired_name = _trim_name(short_name)

            owner_changed = False
            if desired_name:
                cmd = bytes([CMD_SET_ADVERT_NAME]) + desired_name.encode("utf-8", errors="ignore")
                frame = self._request_locked(cmd, expected={RESP_OK, RESP_ERR}, timeout_sec=3.0)
                if frame[0] == RESP_ERR:
                    raise ValueError("set_name_failed")
                self._self_info["node_name"] = desired_name
                owner_changed = True

            reboot_requested = _parse_bool(payload.get("reboot"), False)

            return {
                "status": "ok",
                "data": {
                    "owner_changed": owner_changed,
                    "wifi_changed": False,
                    "reboot_scheduled": False,
                    "reboot_requested": reboot_requested,
                },
            }

    def get_nodes(self) -> dict[str, Any]:
        with self._lock:
            self._ensure_ready_locked()
            contacts = self._refresh_contacts_locked()

            nodes: list[dict[str, Any]] = []

            self_name = self._self_info.get("node_name", "MeshCore Node")
            self_id = self._self_id_locked()
            nodes.append(
                {
                    "num": 0,
                    "id": self_id,
                    "short_name": self_name[:4],
                    "long_name": self_name,
                    "snr": None,
                    "last_heard": int(time.time()),
                    "user": {
                        "id": self_id,
                        "shortName": self_name[:4],
                        "longName": self_name,
                    },
                }
            )

            for c in contacts:
                nodes.append(
                    {
                        "num": 0,
                        "id": c["id"],
                        "short_name": c["name"][:4],
                        "long_name": c["name"],
                        "snr": None,
                        "last_heard": c["last_advert_timestamp"],
                        "user": {
                            "id": c["id"],
                            "shortName": c["name"][:4],
                            "longName": c["name"],
                        },
                    }
                )

            nodes.sort(key=lambda n: (n.get("long_name") or n.get("id") or "").lower())
            return {"status": "ok", "data": {"nodes": nodes}}

    def list_messages(
        self,
        *,
        limit: int,
        include_broadcast: bool,
        include_dm: bool,
        since: int | None,
        peer: str | None,
        channel: int | None,
    ) -> dict[str, Any]:
        with self._lock:
            self._ensure_ready_locked()
            self._poll_messages_locked(max_fetch=200)

            peer_norm = None
            if isinstance(peer, str) and peer.strip():
                try:
                    peer_norm = self._normalize_contact_id_locked(peer)
                except ValueError as exc:
                    raise ValueError("field_peer_invalid") from exc

            filtered: list[dict[str, Any]] = []
            for msg in self._history:
                if since is not None and int(msg.get("timestamp", 0)) <= since:
                    continue

                scope = str(msg.get("scope", ""))
                if scope == "channel" and not include_broadcast:
                    continue
                if scope == "private" and not include_dm:
                    continue

                if channel is not None and int(msg.get("channel", -1)) != channel:
                    continue

                if peer_norm is not None:
                    mid = str(msg.get("peer_id", "")).strip().lower()
                    if mid != peer_norm.lower():
                        continue

                filtered.append(msg)

            if limit > 0:
                filtered = filtered[-limit:]

            return {
                "status": "ok",
                "data": {
                    "count": len(filtered),
                    "messages": filtered,
                },
            }

    def send_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._ensure_ready_locked()
            text = payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("field_text_required")

            text = text.strip()
            if len(text.encode("utf-8")) > MAX_MESSAGE_TEXT:
                raise ValueError("text_too_long")

            to_value = payload.get("to")
            is_private = False
            if isinstance(to_value, str) and to_value.strip() and to_value.strip().lower() not in {
                BROADCAST_ID,
                "4294967295",
                "broadcast",
            }:
                is_private = True

            ts = int(time.time())
            text_bytes = text.encode("utf-8", errors="replace")

            if is_private:
                to_id = self._normalize_contact_id_locked(str(to_value))
                prefix = self._resolve_contact_prefix_locked(to_id)

                cmd = bytes([CMD_SEND_TXT_MSG, TXT_TYPE_PLAIN, 0]) + struct.pack("<I", ts) + prefix + text_bytes
                frame = self._request_locked(cmd, expected={RESP_SENT, RESP_ERR}, timeout_sec=4.0)
                if frame[0] == RESP_ERR:
                    raise ValueError("send_private_failed")

                expected_ack = struct.unpack("<I", frame[2:6])[0] if len(frame) >= 6 else 0
                est_timeout = struct.unpack("<I", frame[6:10])[0] if len(frame) >= 10 else 0

                self._history.append(
                    {
                        "timestamp": ts,
                        "is_boot_relative": False,
                        "channel": 0,
                        "scope": "private",
                        "direction": "out",
                        "sender_num": 0,
                        "sender_id": self._self_id_locked(),
                        "to_num": 0,
                        "to_id": to_id,
                        "peer_num": 0,
                        "peer_id": to_id,
                        "text": text,
                    }
                )

                return {
                    "status": "ok",
                    "data": {
                        "mode": "private",
                        "to": to_id,
                        "packet_id": 0,
                        "want_ack": bool(expected_ack),
                        "est_timeout_ms": est_timeout,
                    },
                }

            channel = _parse_int(str(payload.get("channel", 0)), 0, minimum=0, maximum=7)
            cmd = bytes([CMD_SEND_CHANNEL_TXT_MSG, TXT_TYPE_PLAIN, channel]) + struct.pack("<I", ts) + text_bytes
            frame = self._request_locked(cmd, expected={RESP_OK, RESP_ERR}, timeout_sec=4.0)
            if frame[0] == RESP_ERR:
                raise ValueError("send_channel_failed")

            self._history.append(
                {
                    "timestamp": ts,
                    "is_boot_relative": False,
                    "channel": channel,
                    "scope": "channel",
                    "direction": "out",
                    "sender_num": 0,
                    "sender_id": self._self_id_locked(),
                    "to_num": 0,
                    "to_id": BROADCAST_ID,
                    "peer_num": 0,
                    "peer_id": BROADCAST_ID,
                    "text": text,
                }
            )

            return {
                "status": "ok",
                "data": {
                    "mode": "channel",
                    "channel": channel,
                    "packet_id": 0,
                    "want_ack": False,
                },
            }

    def _close_locked(self, clear_state: bool = True) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except serial.SerialException:
                pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._ser = None
        self._sock = None
        self._ready = False

        if clear_state:
            self._contacts_by_id = {}
            self._device_info = {}
            self._self_info = {}
            self._history.clear()

    def _ensure_ready_locked(self) -> None:
        if self._ready:
            if self._target.get("transport") == "serial" and self._ser is not None and self._ser.is_open:
                return
            if self._target.get("transport") == "tcp" and self._sock is not None:
                return

        self._close_locked(clear_state=False)

        if self._target.get("transport") == "serial":
            serial_port = str(self._target.get("serial_port", ""))
            self._ser = serial.Serial(serial_port, self.baud, timeout=0.15)
            self._ser.reset_input_buffer()
            self._ser.reset_output_buffer()
        else:
            host = str(self._target.get("host", ""))
            port = int(self._target.get("port", 5000))
            self._sock = socket.create_connection((host, port), timeout=2.5)
            self._sock.settimeout(0.15)

        self._ready = False

        dev = self._request_locked(
            bytes([CMD_DEVICE_QUERY, APP_PROTOCOL_VERSION]),
            expected={RESP_DEVICE_INFO},
            timeout_sec=2.5,
        )
        self._device_info = self._parse_device_info_locked(dev)

        app_name = b"mcbridge\x00"
        app_start = bytes([CMD_APP_START, APP_PROTOCOL_VERSION]) + (b"\x00" * 6) + app_name
        info = self._request_locked(app_start, expected={RESP_SELF_INFO}, timeout_sec=2.5)
        self._self_info = self._parse_self_info_locked(info)

        self._ready = True

    def _read_bytes_locked(self, size: int) -> bytes:
        if size <= 0:
            return b""

        if self._ser is not None:
            return self._ser.read(size)
        if self._sock is None:
            raise RuntimeError("transport_not_open")

        try:
            chunk = self._sock.recv(size)
        except socket.timeout:
            return b""
        if not chunk:
            raise OSError("meshcore_tcp_closed")
        return chunk

    def _write_bytes_locked(self, data: bytes) -> None:
        if self._ser is not None:
            self._ser.write(data)
            self._ser.flush()
            return

        if self._sock is None:
            raise RuntimeError("transport_not_open")
        self._sock.sendall(data)

    def _send_frame_locked(self, payload: bytes) -> None:
        frame = b"<" + struct.pack("<H", len(payload)) + payload
        self._write_bytes_locked(frame)

    def _read_frame_locked(self, timeout_sec: float) -> bytes | None:
        if self._ser is None and self._sock is None:
            raise RuntimeError("transport_not_open")

        deadline = time.monotonic() + timeout_sec
        state = 0
        lsb = 0

        while time.monotonic() < deadline:
            b = self._read_bytes_locked(1)
            if not b:
                continue
            c = b[0]

            if state == 0:
                if c == ord(">"):
                    state = 1
                continue

            if state == 1:
                lsb = c
                state = 2
                continue

            frame_len = lsb | (c << 8)
            if frame_len <= 0:
                state = 0
                continue

            remaining = frame_len
            chunks: list[bytes] = []
            while remaining > 0 and time.monotonic() < deadline:
                part = self._read_bytes_locked(remaining)
                if not part:
                    continue
                chunks.append(part)
                remaining -= len(part)

            if remaining == 0:
                return b"".join(chunks)
            return None

        return None

    def _request_locked(self, payload: bytes, *, expected: set[int], timeout_sec: float) -> bytes:
        self._send_frame_locked(payload)
        deadline = time.monotonic() + timeout_sec

        while time.monotonic() < deadline:
            frame = self._read_frame_locked(timeout_sec=max(0.1, deadline - time.monotonic()))
            if frame is None or not frame:
                continue
            code = frame[0]
            if code in expected:
                return frame
            if code >= 0x80:
                continue

        raise TimeoutError(f"meshcore_timeout waiting for {expected}")

    def _parse_device_info_locked(self, frame: bytes) -> dict[str, Any]:
        if len(frame) < 4 or frame[0] != RESP_DEVICE_INFO:
            raise RuntimeError("invalid_device_info")

        out: dict[str, Any] = {
            "firmware_code": frame[1],
            "max_contacts": int(frame[2]) * 2,
            "max_channels": int(frame[3]),
        }

        if len(frame) >= 8:
            out["ble_pin"] = int(struct.unpack("<I", frame[4:8])[0])
        if len(frame) >= 20:
            out["build_date"] = _cstr(frame[8:20])
        if len(frame) >= 60:
            out["manufacturer"] = _cstr(frame[20:60])
        if len(frame) >= 80:
            out["firmware_version"] = _cstr(frame[60:80])
        if len(frame) >= 81:
            out["client_repeat"] = int(frame[80])

        return out

    def _parse_self_info_locked(self, frame: bytes) -> dict[str, Any]:
        if len(frame) < 58 or frame[0] != RESP_SELF_INFO:
            raise RuntimeError("invalid_self_info")

        pubkey = bytes(frame[4:36])
        lat = struct.unpack("<i", frame[36:40])[0] / 1_000_000.0
        lon = struct.unpack("<i", frame[40:44])[0] / 1_000_000.0
        freq_mhz = struct.unpack("<I", frame[48:52])[0] / 1000.0
        bw_khz = struct.unpack("<I", frame[52:56])[0] / 1000.0

        node_name = frame[58:].decode("utf-8", errors="replace").strip() or "MeshCore Node"

        return {
            "adv_type": int(frame[1]),
            "tx_power_dbm": int(frame[2]),
            "max_tx_power_dbm": int(frame[3]),
            "pubkey": pubkey,
            "lat": lat,
            "lon": lon,
            "multi_acks": int(frame[44]),
            "advert_loc_policy": int(frame[45]),
            "telem_mode": int(frame[46]),
            "manual_add_contacts": int(frame[47]),
            "freq_mhz": freq_mhz,
            "bw_khz": bw_khz,
            "sf": int(frame[56]),
            "cr": int(frame[57]),
            "node_name": node_name,
        }

    def _self_id_locked(self) -> str:
        pubkey = self._self_info.get("pubkey", b"")
        if isinstance(pubkey, (bytes, bytearray)) and len(pubkey) >= 6:
            return _id_from_prefix(bytes(pubkey[:6]))
        return "!unknown"

    def _normalize_contact_id_locked(self, raw: str) -> str:
        value = raw.strip().lower()
        if value.startswith("mc:"):
            value = value[3:]
        if value.startswith("!"):
            value = value[1:]
        value = value.replace(":", "")

        if len(value) >= 12 and all(c in "0123456789abcdef" for c in value[:12]):
            return f"!{value[:12]}"

        for cid, c in self._contacts_by_id.items():
            cid_low = cid.lower()
            if value and value in {cid_low, cid_low.lstrip("!"), c.get("name", "").lower()}:
                return cid

        raise ValueError("field_to_invalid")

    def _resolve_contact_prefix_locked(self, contact_id: str) -> bytes:
        c = self._contacts_by_id.get(contact_id)
        if c and isinstance(c.get("prefix"), (bytes, bytearray)) and len(c["prefix"]) == 6:
            return bytes(c["prefix"])
        raise ValueError("field_to_not_found")

    def _refresh_contacts_locked(self) -> list[dict[str, Any]]:
        self._send_frame_locked(bytes([CMD_GET_CONTACTS]))

        contacts: list[dict[str, Any]] = []
        got_start = False
        deadline = time.monotonic() + 5.0

        while time.monotonic() < deadline:
            frame = self._read_frame_locked(timeout_sec=0.6)
            if frame is None or not frame:
                continue

            code = frame[0]
            if code == RESP_CONTACTS_START:
                got_start = True
                continue
            if code == RESP_CONTACT:
                if len(frame) < 148:
                    continue
                pubkey = bytes(frame[1:33])
                prefix = bytes(frame[1:7])
                name = _cstr(frame[100:132]) or _id_from_prefix(prefix)
                last_advert_ts = struct.unpack("<I", frame[132:136])[0]
                lastmod = struct.unpack("<I", frame[144:148])[0]
                cid = _id_from_prefix(prefix)
                contacts.append(
                    {
                        "id": cid,
                        "prefix": prefix,
                        "pubkey": pubkey,
                        "name": name,
                        "type": int(frame[33]),
                        "flags": int(frame[34]),
                        "last_advert_timestamp": int(last_advert_ts),
                        "lastmod": int(lastmod),
                    }
                )
                continue
            if code == RESP_END_OF_CONTACTS:
                break
            if code >= 0x80:
                continue

        if got_start:
            self._contacts_by_id = {c["id"]: c for c in contacts}
        return contacts

    def _poll_messages_locked(self, max_fetch: int) -> None:
        for _ in range(max_fetch):
            frame = self._request_locked(
                bytes([CMD_SYNC_NEXT_MESSAGE]),
                expected={
                    RESP_NO_MORE_MESSAGES,
                    RESP_CONTACT_MSG_RECV,
                    RESP_CHANNEL_MSG_RECV,
                    RESP_CONTACT_MSG_RECV_V3,
                    RESP_CHANNEL_MSG_RECV_V3,
                },
                timeout_sec=1.5,
            )

            code = frame[0]
            if code == RESP_NO_MORE_MESSAGES:
                return

            msg = self._decode_message_locked(frame)
            if msg is not None:
                self._history.append(msg)

    def _decode_message_locked(self, frame: bytes) -> dict[str, Any] | None:
        code = frame[0]

        if code in {RESP_CONTACT_MSG_RECV, RESP_CONTACT_MSG_RECV_V3}:
            if code == RESP_CONTACT_MSG_RECV_V3:
                if len(frame) < 16:
                    return None
                sender_prefix = bytes(frame[4:10])
                txt_type = int(frame[11])
                ts = struct.unpack("<I", frame[12:16])[0]
                payload = frame[16:]
            else:
                if len(frame) < 13:
                    return None
                sender_prefix = bytes(frame[1:7])
                txt_type = int(frame[8])
                ts = struct.unpack("<I", frame[9:13])[0]
                payload = frame[13:]

            if txt_type == TXT_TYPE_SIGNED_PLAIN and len(payload) >= 4:
                payload = payload[4:]

            text = payload.decode("utf-8", errors="replace").strip()
            sender_id = _id_from_prefix(sender_prefix)
            self_id = self._self_id_locked()

            return {
                "timestamp": int(ts),
                "is_boot_relative": False,
                "channel": 0,
                "scope": "private",
                "direction": "in",
                "sender_num": 0,
                "sender_id": sender_id,
                "to_num": 0,
                "to_id": self_id,
                "peer_num": 0,
                "peer_id": sender_id,
                "text": text,
            }

        if code in {RESP_CHANNEL_MSG_RECV, RESP_CHANNEL_MSG_RECV_V3}:
            if code == RESP_CHANNEL_MSG_RECV_V3:
                if len(frame) < 11:
                    return None
                channel = int(frame[4])
                ts = struct.unpack("<I", frame[7:11])[0]
                payload = frame[11:]
            else:
                if len(frame) < 8:
                    return None
                channel = int(frame[1])
                ts = struct.unpack("<I", frame[4:8])[0]
                payload = frame[8:]

            text = payload.decode("utf-8", errors="replace").strip()
            self_id = self._self_id_locked()

            return {
                "timestamp": int(ts),
                "is_boot_relative": False,
                "channel": channel,
                "scope": "channel",
                "direction": "in",
                "sender_num": 0,
                "sender_id": "mc:channel",
                "to_num": 0,
                "to_id": BROADCAST_ID,
                "peer_num": 0,
                "peer_id": BROADCAST_ID,
                "text": text,
                "local_id": self_id,
            }

        return None


@dataclass
class AppState:
    serial_port: str
    baud: int
    client: MeshCoreClient


class MeshCoreJsonHandler(BaseHTTPRequestHandler):
    state = AppState(serial_port="/dev/ttyUSB0", baud=115200, client=MeshCoreClient("/dev/ttyUSB0", 115200))
    index_html = INDEX_HTML.read_bytes() if INDEX_HTML.exists() else b""

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)

    def do_OPTIONS(self) -> None:
        if self.path.startswith("/api/") or self.path.startswith("/json/"):
            self.send_response(204)
            self._set_json_headers()
            self.end_headers()
            return
        self.send_error(404)

    def do_GET(self) -> None:
        parsed = parse.urlsplit(self.path)

        if parsed.path in {"/", "/index.html"}:
            if not self.index_html:
                self._send_json(500, {"status": "error", "error": "missing_index_html"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(self.index_html)))
            self.end_headers()
            self.wfile.write(self.index_html)
            return

        if parsed.path == "/api/config":
            cfg = self.state.client.get_config()
            self._send_json(200, {"status": "ok", **cfg})
            return

        if parsed.path in {"/json/report", "/api/report"}:
            self._call_client_json(self.state.client.get_report)
            return

        if parsed.path in {"/json/config/node", "/api/node-config"}:
            self._call_client_json(self.state.client.get_node_config)
            return

        if parsed.path in {"/json/nodes", "/api/nodes"}:
            self._call_client_json(self.state.client.get_nodes)
            return

        if parsed.path in {"/json/chat/messages", "/api/messages"}:
            params = parse.parse_qs(parsed.query)
            limit = _parse_int(params.get("limit", ["30"])[0], 30, minimum=1, maximum=100)
            include_broadcast = _parse_bool(params.get("includeBroadcast", ["true"])[0], True)
            include_dm = _parse_bool(params.get("includeDm", ["true"])[0], True)
            since_raw = params.get("since", [None])[0]
            since = _parse_int(since_raw, 0, minimum=0) if since_raw not in (None, "") else None
            peer = params.get("peer", [""])[0] or None
            ch_raw = params.get("channel", [None])[0]
            channel = _parse_int(ch_raw, 0, minimum=0, maximum=7) if ch_raw not in (None, "") else None

            self._call_client_json(
                lambda: self.state.client.list_messages(
                    limit=limit,
                    include_broadcast=include_broadcast,
                    include_dm=include_dm,
                    since=since,
                    peer=peer,
                    channel=channel,
                ),
                bad_request_is_400=True,
            )
            return

        self._send_json(404, {"status": "error", "error": "not_found"})

    def do_POST(self) -> None:
        parsed = parse.urlsplit(self.path)

        if parsed.path == "/api/config":
            body = self._read_json_body()
            if body is None:
                return

            raw_target = body.get("serial_port")
            if raw_target is None:
                raw_target = body.get("esp_base_url")
            if not isinstance(raw_target, str) or not raw_target.strip():
                self._send_json(400, {"status": "error", "error": "field_serial_port_required"})
                return

            baud = _parse_int(str(body.get("baud", self.state.baud)), self.state.baud, minimum=9600, maximum=921600)

            try:
                target_spec = _parse_target(raw_target, baud)
                target = _target_string(target_spec)
                self.state.serial_port = target
                self.state.baud = baud
                self.state.client.set_serial(target, baud)
                # Probe connection immediately so config errors are surfaced now.
                self.state.client.get_report()
                cfg = self.state.client.get_config()
                self._send_json(200, {"status": "ok", **cfg})
            except ValueError as exc:
                self._send_json(400, {"status": "error", "error": "field_serial_port_invalid", "detail": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._send_json(400, {"status": "error", "error": "invalid_serial_config", "detail": str(exc)})
            return

        if parsed.path in {"/json/chat/send", "/api/send"}:
            body = self._read_json_body()
            if body is None:
                return
            self._call_client_json(lambda: self.state.client.send_message(body), bad_request_is_400=True)
            return

        if parsed.path in {"/json/config/node", "/api/node-config"}:
            body = self._read_json_body()
            if body is None:
                return
            self._call_client_json(lambda: self.state.client.set_node_config(body), bad_request_is_400=True)
            return

        self._send_json(404, {"status": "error", "error": "not_found"})

    def _set_json_headers(self) -> None:
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-store")

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status_code)
        self._set_json_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            logging.debug("Client disconnected while sending response")

    def _read_json_body(self) -> dict[str, Any] | None:
        content_length = self.headers.get("Content-Length", "")
        try:
            body_size = int(content_length)
        except ValueError:
            self._send_json(400, {"status": "error", "error": "invalid_content_length"})
            return None

        if body_size <= 0:
            self._send_json(400, {"status": "error", "error": "missing_body"})
            return None
        if body_size > MAX_REQUEST_BODY:
            self._send_json(413, {"status": "error", "error": "body_too_large"})
            return None

        raw = self.rfile.read(body_size)
        try:
            parsed: Any = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"status": "error", "error": "invalid_json"})
            return None

        if not isinstance(parsed, dict):
            self._send_json(400, {"status": "error", "error": "json_object_required"})
            return None

        return parsed

    def _call_client_json(self, fn: Any, bad_request_is_400: bool = False) -> None:
        try:
            payload = fn()
            self._send_json(200, payload)
        except ValueError as exc:
            status = 400 if bad_request_is_400 else 502
            self._send_json(status, {"status": "error", "error": str(exc)})
        except (serial.SerialException, TimeoutError, OSError) as exc:
            # Drop broken transport state so the next request can reconnect cleanly.
            try:
                self.state.client.close()
            except Exception:  # noqa: BLE001
                pass
            self._send_json(502, {"status": "error", "error": "meshcore_unreachable", "detail": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logging.exception("Unhandled bridge error")
            self._send_json(500, {"status": "error", "error": "internal_error", "detail": str(exc)})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve MeshCore JSON Bridge web UI")
    parser.add_argument("--host", default="127.0.0.1", help="Host/IP to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8865, help="HTTP port (default: 8865)")
    parser.add_argument(
        "--target",
        default="/dev/ttyUSB0",
        help="MeshCore transport target, e.g. /dev/ttyUSB0 or tcp://192.168.1.50:5000",
    )
    parser.add_argument("--serial-port", dest="target", help=argparse.SUPPRESS)
    parser.add_argument("--baud", type=int, default=115200, help="MeshCore serial baud rate (default: 115200)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not INDEX_HTML.exists():
        raise SystemExit(f"Missing UI file: {INDEX_HTML}")

    client = MeshCoreClient(serial_port=args.target, baud=args.baud)
    MeshCoreJsonHandler.state = AppState(serial_port=args.target, baud=args.baud, client=client)
    MeshCoreJsonHandler.index_html = INDEX_HTML.read_bytes()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with ThreadingHTTPServer((args.host, args.port), MeshCoreJsonHandler) as server:
        logging.info("MeshCore JSON Bridge UI: http://%s:%d", args.host, args.port)
        logging.info("MeshCore target: %s (baud %d for serial)", args.target, args.baud)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logging.info("Stopping bridge server")
        finally:
            client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
