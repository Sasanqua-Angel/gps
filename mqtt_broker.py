"""Embedded lightweight MQTT broker for local teaching/demo use.

The broker implements the small subset this project needs:
CONNECT, PUBLISH QoS0, SUBSCRIBE QoS0, PINGREQ, and DISCONNECT.
"""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass, field
from typing import Callable, List, Tuple

from mqtt_packet import (
    MQTT_CONNECT,
    MQTT_DISCONNECT,
    MQTT_PINGREQ,
    MQTT_PINGRESP,
    MQTT_PUBLISH,
    MQTT_SUBACK,
    MQTT_SUBSCRIBE,
    build_publish_packet,
    decode_utf8,
    parse_publish_packet,
    read_remaining_length,
    topic_matches,
)


MessageCallback = Callable[[str, bytes], None]


@dataclass
class BrokerSession:
    sock: socket.socket
    address: tuple
    client_id: str = ""
    subscriptions: List[str] = field(default_factory=list)


class MQTTBroker:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883):
        self.host = host
        self.port = port
        self._server_socket: socket.socket | None = None
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._sessions: List[BrokerSession] = []
        self._internal_subscribers: List[Tuple[str, MessageCallback]] = []
        self._lock = threading.Lock()

    def subscribe_internal(self, topic_filter: str, callback: MessageCallback) -> None:
        with self._lock:
            self._internal_subscribers.append((topic_filter, callback))

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._running.set()
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind((self.host, self.port))
        self._server_socket.listen()
        self._thread = threading.Thread(target=self._accept_loop, name="mqtt-broker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass

        with self._lock:
            sessions = list(self._sessions)
        for session in sessions:
            self._close_session(session)

    def _accept_loop(self) -> None:
        assert self._server_socket is not None
        while self._running.is_set():
            try:
                client_sock, address = self._server_socket.accept()
            except OSError:
                break
            session = BrokerSession(client_sock, address)
            with self._lock:
                self._sessions.append(session)
            threading.Thread(target=self._client_loop, args=(session,), daemon=True).start()

    def _client_loop(self, session: BrokerSession) -> None:
        session.sock.settimeout(120)
        try:
            while self._running.is_set():
                first = session.sock.recv(1)
                if not first:
                    break

                header_byte = first[0]
                packet_type = header_byte >> 4
                remaining_length = read_remaining_length(session.sock)
                body = self._recv_exact(session.sock, remaining_length)

                if packet_type == MQTT_CONNECT:
                    session.client_id = self._parse_connect_client_id(body)
                    session.sock.sendall(b"\x20\x02\x00\x00")
                elif packet_type == MQTT_PUBLISH:
                    topic, payload, _retain = parse_publish_packet(header_byte, body)
                    self._dispatch(topic, payload)
                elif packet_type == MQTT_SUBSCRIBE:
                    self._handle_subscribe(session, body)
                elif packet_type == MQTT_PINGREQ:
                    session.sock.sendall(bytes([(MQTT_PINGRESP << 4), 0]))
                elif packet_type == MQTT_DISCONNECT:
                    break
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            self._close_session(session)

    def _dispatch(self, topic: str, payload: bytes) -> None:
        with self._lock:
            callbacks = list(self._internal_subscribers)
            sessions = list(self._sessions)

        for topic_filter, callback in callbacks:
            if topic_matches(topic_filter, topic):
                callback(topic, payload)

        packet = build_publish_packet(topic, payload)
        for session in sessions:
            if any(topic_matches(topic_filter, topic) for topic_filter in session.subscriptions):
                try:
                    session.sock.sendall(packet)
                except OSError:
                    self._close_session(session)

    def _handle_subscribe(self, session: BrokerSession, body: bytes) -> None:
        if len(body) < 5:
            raise ValueError("invalid SUBSCRIBE packet")

        packet_id = body[:2]
        offset = 2
        granted_qos = []
        while offset < len(body):
            topic_filter, offset = decode_utf8(body, offset)
            if offset >= len(body):
                raise ValueError("missing requested QoS")
            offset += 1
            session.subscriptions.append(topic_filter)
            granted_qos.append(0)

        remaining_length = 2 + len(granted_qos)
        session.sock.sendall(bytes([(MQTT_SUBACK << 4), remaining_length]) + packet_id + bytes(granted_qos))

    def _parse_connect_client_id(self, body: bytes) -> str:
        protocol_name, offset = decode_utf8(body, 0)
        if protocol_name != "MQTT":
            raise ValueError("only MQTT 3.1.1 protocol name is supported")
        offset += 4
        client_id, _ = decode_utf8(body, offset)
        return client_id

    def _recv_exact(self, sock: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("socket closed")
            data.extend(chunk)
        return bytes(data)

    def _close_session(self, session: BrokerSession) -> None:
        with self._lock:
            if session in self._sessions:
                self._sessions.remove(session)
        try:
            session.sock.close()
        except OSError:
            pass

