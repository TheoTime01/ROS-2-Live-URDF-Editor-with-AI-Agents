# Copyright 2026 theotime01
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Standard-library HTTP + WebSocket transport for :class:`WebApiService`.

This module is the thin edge that puts the transport-agnostic service onto a
real socket, using only the Python standard library so the package pulls in no
extra rosdep. REST requests are dispatched to ``service.handle``; a WebSocket
``GET`` on the event path (default ``/events``) is upgraded per RFC 6455, sent a
``snapshot`` frame, and then fed every event the service publishes on its hub.

The WebSocket framing here is deliberately minimal: the server sends unmasked
text frames and understands client ``close``/``ping`` control frames, which is
all the event stream needs. Nothing in this file imports rclpy; ``web_api_node``
owns the ROS wiring.
"""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import select
import threading

#: Magic GUID from RFC 6455 used to derive the handshake accept token.
_WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

# WebSocket opcodes (the subset this server acts on).
_OP_TEXT = 0x1
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


def _accept_key(key):
    """Return the ``Sec-WebSocket-Accept`` value for a client ``key``."""
    digest = hashlib.sha1((key + _WS_GUID).encode('utf-8')).digest()
    return base64.b64encode(digest).decode('ascii')


def encode_frame(opcode, payload):
    """Encode one unmasked server frame carrying ``payload`` bytes."""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += length.to_bytes(2, 'big')
    else:
        header.append(127)
        header += length.to_bytes(8, 'big')
    return bytes(header) + payload


def _read_exactly(stream, count):
    """Read exactly ``count`` bytes from ``stream`` or return ``None``."""
    if count == 0:
        return b''
    data = stream.read(count)
    if data is None or len(data) < count:
        return None
    return data


def read_frame(stream):
    """Read one (possibly masked) client frame as ``(opcode, payload)``."""
    header = _read_exactly(stream, 2)
    if header is None:
        return None
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F
    if length == 126:
        extended = _read_exactly(stream, 2)
        if extended is None:
            return None
        length = int.from_bytes(extended, 'big')
    elif length == 127:
        extended = _read_exactly(stream, 8)
        if extended is None:
            return None
        length = int.from_bytes(extended, 'big')
    mask = _read_exactly(stream, 4) if masked else b''
    if mask is None:
        return None
    payload = _read_exactly(stream, length)
    if payload is None:
        return None
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def make_handler(service, event_path, poll_interval, stop_event):
    """Build a request handler class bound to ``service`` and the stop event."""

    class _Handler(BaseHTTPRequestHandler):
        """Serve REST requests and upgrade the event path to WebSocket."""

        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            """Silence the default per-request stderr logging."""

        def do_GET(self):
            """Route a GET to either the WebSocket upgrade or REST."""
            if self._wants_websocket() and self._route() == event_path:
                self._serve_websocket()
            else:
                self._serve_rest('GET')

        def do_POST(self):
            """Route a POST to the REST dispatcher."""
            self._serve_rest('POST')

        def _route(self):
            """Return the request path without its query string."""
            return self.path.split('?', 1)[0]

        def _wants_websocket(self):
            """Return ``True`` when the request is a WebSocket upgrade."""
            upgrade = self.headers.get('Upgrade', '')
            connection = self.headers.get('Connection', '')
            return (upgrade.lower() == 'websocket'
                    and 'upgrade' in connection.lower())

        def _read_body(self):
            """Read the request body according to ``Content-Length``."""
            length = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(length) if length else b''

        def _serve_rest(self, method):
            """Dispatch a REST request and write the JSON response.

            ``service.handle`` is total: it maps every request -- valid or not
            -- to an :class:`ApiResponse`, so no error handling is needed here.
            """
            response = service.handle(method, self.path, self._read_body())
            payload = response.to_json().encode('utf-8')
            self.send_response(response.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        # -- WebSocket -----------------------------------------------------

        def _serve_websocket(self):
            """Complete the handshake and stream events until closed."""
            key = self.headers.get('Sec-WebSocket-Key')
            if not key:
                self.send_error(400, 'missing Sec-WebSocket-Key')
                return
            self.send_response(101, 'Switching Protocols')
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', _accept_key(key))
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            subscription = service.hub.subscribe()
            try:
                if not self._ws_send(json.dumps(service.snapshot_event())):
                    return
                self._ws_stream(subscription)
            finally:
                subscription.close()

        def _ws_stream(self, subscription):
            """Pump published events out and watch for a client close."""
            sock = self.connection
            while not stop_event.is_set():
                readable, _, _ = select.select([sock], [], [], poll_interval)
                if readable and not self._ws_drain_incoming():
                    return
                if not self._ws_flush(subscription):
                    return

        def _ws_drain_incoming(self):
            """Handle a client frame; return ``False`` to close the stream."""
            frame = read_frame(self.rfile)
            if frame is None:
                return False
            opcode, payload = frame
            if opcode == _OP_CLOSE:
                return False
            if opcode == _OP_PING:
                return self._ws_send_frame(_OP_PONG, payload)
            return True

        def _ws_flush(self, subscription):
            """Send every queued event; return ``False`` on write failure."""
            while True:
                try:
                    event = subscription.get_nowait()
                except queue.Empty:
                    return True
                if not self._ws_send(json.dumps(event)):
                    return False

        def _ws_send(self, text):
            """Send ``text`` as a WebSocket text frame."""
            return self._ws_send_frame(_OP_TEXT, text.encode('utf-8'))

        def _ws_send_frame(self, opcode, payload):
            """Write one frame, returning ``False`` if the socket is gone."""
            try:
                self.wfile.write(encode_frame(opcode, payload))
                self.wfile.flush()
                return True
            except OSError:
                return False

    return _Handler


class WebApiServer:
    """A threaded HTTP + WebSocket server in front of a :class:`WebApiService`."""

    def __init__(self, service, host='127.0.0.1', port=8080,
                 event_path='/events', poll_interval=0.2):
        """Bind a threaded HTTP server routing to ``service``."""
        self._service = service
        self._stop_event = threading.Event()
        handler = make_handler(
            service, event_path, poll_interval, self._stop_event)
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        self._thread = None

    @property
    def host(self):
        """Return the bound host address."""
        return self._httpd.server_address[0]

    @property
    def port(self):
        """Return the bound TCP port, chosen by the OS when bound to 0."""
        return self._httpd.server_address[1]

    def start(self):
        """Serve in a background thread and return ``self``."""
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name='web_api_server',
            daemon=True)
        self._thread.start()
        return self

    def serve_forever(self):
        """Serve in the calling thread until :meth:`stop` is called."""
        self._httpd.serve_forever()

    def stop(self):
        """Stop serving and tear down open WebSocket streams."""
        self._stop_event.set()
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
