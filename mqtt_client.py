"""Minimal MQTT publisher client used by the simulated GPS device."""

from __future__ import annotations

import socket
import time

from mqtt_packet import MQTT_DISCONNECT, MQTT_PINGREQ, build_publish_packet, encode_remaining_length, encode_utf8


class MQTTClient:
    def __init__(self, host: str, port: int, client_id: str, keepalive: int = 60):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.keepalive = keepalive
        self.sock: socket.socket | None = None
        self._last_io = 0.0

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=10)
        variable_header = encode_utf8("MQTT") + bytes([4, 2]) + self.keepalive.to_bytes(2, "big")
        payload = encode_utf8(self.client_id)
        packet = b"\x10" + encode_remaining_length(len(variable_header) + len(payload)) + variable_header + payload
        self.sock.sendall(packet)

        response = self.sock.recv(4)
        if response != b"\x20\x02\x00\x00":
            raise ConnectionError(f"MQTT CONNACK failed: {response!r}")
        self._last_io = time.time()

    def publish(self, topic: str, payload: bytes | str) -> None:
        if self.sock is None:
            raise ConnectionError("MQTT client is not connected")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        self.sock.sendall(build_publish_packet(topic, payload))
        self._last_io = time.time()

    def ping_if_needed(self) -> None:
        if self.sock is None:
            return
        if time.time() - self._last_io > self.keepalive / 2:
            self.sock.sendall(bytes([(MQTT_PINGREQ << 4), 0]))
            self.sock.recv(2)
            self._last_io = time.time()

    def disconnect(self) -> None:
        if self.sock is None:
            return
        try:
            self.sock.sendall(bytes([(MQTT_DISCONNECT << 4), 0]))
        finally:
            self.sock.close()
            self.sock = None

