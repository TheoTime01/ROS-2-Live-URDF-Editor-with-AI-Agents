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
End-to-end wire tests for the HTTP + WebSocket transport.

These bring up :class:`WebApiServer` on a real ephemeral port and drive it the
way an external client would: REST over ``http.client`` and the event stream
over a hand-rolled WebSocket client (stdlib sockets only). This is the
Milestone 3 proof that the edit flow is genuinely drivable over the wire and
that live model events reach a WebSocket subscriber.
"""

import base64
import http.client
import json
import os
import socket

import pytest

from urdf_live_editor.web.server import WebApiServer
from urdf_live_editor.web.service import WebApiService

VALID = ('<robot name="r"><link name="base"/><link name="l1"/>'
         '<joint name="j1" type="revolute">'
         '<parent link="base"/><child link="l1"/>'
         '<axis xyz="0 0 1"/>'
         '<limit lower="-1" upper="1" effort="5" velocity="1"/>'
         '</joint></robot>')

ADD_L2 = [
    {'op': 'add_link', 'name': 'l2'},
    {'op': 'add_joint', 'name': 'j2', 'joint_type': 'continuous',
     'parent': 'l1', 'child': 'l2', 'axis': [0, 0, 1]},
]


@pytest.fixture()
def server():
    """Start a web API server on an ephemeral port and tear it down after."""
    service = WebApiService.from_urdf(VALID)
    api = WebApiServer(service, host='127.0.0.1', port=0,
                       poll_interval=0.05).start()
    try:
        yield api
    finally:
        api.stop()


def _request(api, method, path, body=None):
    """Perform one REST request and return ``(status, parsed_json)``."""
    conn = http.client.HTTPConnection(api.host, api.port, timeout=5)
    try:
        payload = json.dumps(body) if body is not None else None
        headers = {'Content-Type': 'application/json'} if payload else {}
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        data = response.read().decode('utf-8')
        return response.status, json.loads(data)
    finally:
        conn.close()


def test_rest_edit_flow_over_http(server):
    """Read, apply, and re-read the model over real HTTP requests."""
    status, body = _request(server, 'GET', '/model')
    assert status == 200
    assert body['version']['index'] == 0

    status, body = _request(server, 'POST', '/apply', {'operations': ADD_L2})
    assert status == 200
    assert body['applied'] is True
    assert body['version']['index'] == 1

    status, body = _request(server, 'GET', '/model')
    assert status == 200
    assert body['version']['index'] == 1
    assert 'l2' in body['urdf']


def test_rest_rejects_invalid_edit_over_http(server):
    """A validation failure comes back as a 422 across the wire."""
    ops = [{'op': 'add_joint', 'name': 'jx', 'joint_type': 'fixed',
            'parent': 'ghost', 'child': 'l1'}]
    status, body = _request(server, 'POST', '/apply', {'operations': ops})
    assert status == 422
    assert body['applied'] is False


class _WebSocketClient:
    """A minimal RFC 6455 client: handshake, then read server text frames."""

    def __init__(self, host, port, path):
        """Open the socket and complete the upgrade handshake."""
        self._sock = socket.create_connection((host, port), timeout=5)
        self._sock.settimeout(5)
        self._reader = self._sock.makefile('rb')
        self._handshake(host, port, path)

    def _handshake(self, host, port, path):
        """Send the upgrade request and consume the 101 response."""
        key = base64.b64encode(os.urandom(16)).decode('ascii')
        request = (
            'GET %s HTTP/1.1\r\n'
            'Host: %s:%d\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            'Sec-WebSocket-Key: %s\r\n'
            'Sec-WebSocket-Version: 13\r\n\r\n'
            % (path, host, port, key))
        self._sock.sendall(request.encode('ascii'))
        status_line = self._reader.readline().decode('ascii')
        assert '101' in status_line, status_line
        while True:
            line = self._reader.readline()
            if line in (b'\r\n', b'\n', b''):
                break

    def recv_json(self):
        """Read one server text frame and parse it as JSON."""
        header = self._reader.read(2)
        assert len(header) == 2
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(self._reader.read(2), 'big')
        elif length == 127:
            length = int.from_bytes(self._reader.read(8), 'big')
        payload = self._reader.read(length)
        return json.loads(payload.decode('utf-8'))

    def close(self):
        """Close the reader and underlying socket."""
        try:
            self._reader.close()
        finally:
            self._sock.close()


def test_websocket_streams_snapshot_then_events(server):
    """A WebSocket client gets a snapshot, then live model events."""
    client = _WebSocketClient(server.host, server.port, '/events')
    try:
        snapshot = client.recv_json()
        assert snapshot['type'] == 'snapshot'
        assert snapshot['version']['index'] == 0

        status, _ = _request(
            server, 'POST', '/apply', {'operations': ADD_L2})
        assert status == 200

        event = client.recv_json()
        assert event['type'] == 'applied'
        assert event['diff']['added_links'] == ['l2']
    finally:
        client.close()
