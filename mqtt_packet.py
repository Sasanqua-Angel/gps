"""Small MQTT 3.1.1 helpers used by the simulator and embedded broker."""

from __future__ import annotations

import socket
from typing import Tuple


MQTT_CONNECT = 1
MQTT_CONNACK = 2
MQTT_PUBLISH = 3
MQTT_SUBSCRIBE = 8
MQTT_SUBACK = 9
MQTT_PINGREQ = 12
MQTT_PINGRESP = 13
MQTT_DISCONNECT = 14


def encode_remaining_length(value: int) -> bytes:
    if value < 0:
        raise ValueError("remaining length must be non-negative")

    encoded = bytearray()
    while True:
        digit = value % 128
        value //= 128
        if value > 0:
            digit |= 0x80
        encoded.append(digit)
        if value == 0:
            return bytes(encoded)


def decode_remaining_length(data: bytes) -> Tuple[int, int]:
    multiplier = 1
    value = 0

    for index, encoded_byte in enumerate(data, start=1):
        value += (encoded_byte & 127) * multiplier
        if (encoded_byte & 128) == 0:
            return value, index
        multiplier *= 128
        if multiplier > 128 * 128 * 128:
            raise ValueError("malformed MQTT remaining length")

    raise ValueError("incomplete MQTT remaining length")


def read_remaining_length(sock: socket.socket) -> int:
    data = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("socket closed while reading MQTT remaining length")
        data.extend(chunk)
        if chunk[0] & 0x80 == 0:
            value, _ = decode_remaining_length(bytes(data))
            return value
        if len(data) >= 4:
            raise ValueError("malformed MQTT remaining length")


def encode_utf8(text: str) -> bytes:
    payload = text.encode("utf-8")
    if len(payload) > 65_535:
        raise ValueError("MQTT UTF-8 field is too long")
    return len(payload).to_bytes(2, "big") + payload


def decode_utf8(data: bytes, offset: int = 0) -> Tuple[str, int]:
    if offset + 2 > len(data):
        raise ValueError("missing MQTT UTF-8 length")
    length = int.from_bytes(data[offset : offset + 2], "big")
    start = offset + 2
    end = start + length
    if end > len(data):
        raise ValueError("incomplete MQTT UTF-8 field")
    return data[start:end].decode("utf-8"), end


def build_publish_packet(topic: str, payload: bytes, retain: bool = False) -> bytes:
    fixed_header = (MQTT_PUBLISH << 4) | (1 if retain else 0)
    variable_header = encode_utf8(topic)
    remaining_length = len(variable_header) + len(payload)
    return bytes([fixed_header]) + encode_remaining_length(remaining_length) + variable_header + payload


def parse_publish_packet(header_byte: int, body: bytes) -> Tuple[str, bytes, bool]:
    topic, offset = decode_utf8(body, 0)
    qos = (header_byte >> 1) & 0x03
    if qos:
        offset += 2
    retain = bool(header_byte & 0x01)
    return topic, body[offset:], retain


def topic_matches(filter_topic: str, topic: str) -> bool:
    filter_parts = filter_topic.split("/")
    topic_parts = topic.split("/")

    for index, filter_part in enumerate(filter_parts):
        if filter_part == "#":
            return index == len(filter_parts) - 1
        if index >= len(topic_parts):
            return False
        if filter_part != "+" and filter_part != topic_parts[index]:
            return False

    return len(topic_parts) == len(filter_parts)

