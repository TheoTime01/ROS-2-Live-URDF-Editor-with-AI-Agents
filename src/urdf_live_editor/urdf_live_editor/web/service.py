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
Transport-agnostic web-API service over the edit pipeline.

:class:`WebApiService` is the deterministic, offline-testable core of
``web_api_node``: it wraps a
:class:`~urdf_live_editor.model_update_coordinator_node.ModelUpdateCoordinator`
and turns request tuples ``(method, path, body)`` into :class:`ApiResponse`
values, without ever touching a socket or importing rclpy. Every mutating
request also emits an event on an :class:`~urdf_live_editor.web.events.EventHub`
so a WebSocket stream can broadcast live validation diagnostics and model
changes, and an optional ``on_commit`` callback lets the ROS node republish
``robot_description`` whenever an applied edit or rollback changes the model.

The same stage -> validate -> apply/reject discipline the coordinator enforces
is preserved here: the API is just another front end onto the trusted core, so
it can never bypass validation.
"""

import json
import threading

from urdf_live_editor.model.edit_ops import EditError, operations_from_dicts
from urdf_live_editor.model_update_coordinator_node import (
    ModelUpdateCoordinator)
from urdf_live_editor.validation.engine import validate_urdf_string
from urdf_live_editor.web.events import EventHub


class ApiError(Exception):
    """A request error carrying the HTTP status and a machine code."""

    def __init__(self, status, code, message):
        """Record ``status`` (HTTP code), a short ``code``, and ``message``."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ApiResponse:
    """A status code plus a JSON-serializable body."""

    def __init__(self, status, body):
        """Bundle an HTTP ``status`` with its ``body`` dict."""
        self.status = status
        self.body = body

    def to_json(self):
        """Serialize the body to a compact JSON string."""
        return json.dumps(self.body)


def _version_dict(version):
    """Return a JSON-serializable view of a :class:`Version`."""
    return {
        'index': version.index,
        'label': version.label,
        'parent': version.parent,
        'operations': list(version.operations),
        'timestamp': version.timestamp,
    }


class WebApiService:
    """Route REST requests onto the coordinator and emit stream events."""

    def __init__(self, coordinator, hub=None, on_commit=None):
        """Wrap ``coordinator``, publishing events on ``hub`` (created if None)."""
        self._coordinator = coordinator
        self._hub = hub if hub is not None else EventHub()
        self._on_commit = on_commit
        self._lock = threading.Lock()

    @classmethod
    def from_urdf(cls, xml_str, hub=None, on_commit=None, label='initial'):
        """Build a service from a URDF string, requiring it to be valid."""
        coordinator = ModelUpdateCoordinator.from_urdf(xml_str, label=label)
        return cls(coordinator, hub=hub, on_commit=on_commit)

    @property
    def hub(self):
        """Return the event hub this service publishes to."""
        return self._hub

    @property
    def coordinator(self):
        """Return the wrapped coordinator."""
        return self._coordinator

    def snapshot_event(self):
        """Return the ``snapshot`` event describing the current model."""
        with self._lock:
            version = self._coordinator.current_version
            return {
                'type': 'snapshot',
                'version': _version_dict(version),
                'urdf': self._coordinator.current_urdf(),
                'validation': self._coordinator.validate_current().to_dict(),
            }

    def handle(self, method, path, body=b''):
        """Dispatch one request, always returning an :class:`ApiResponse`."""
        route = path.split('?', 1)[0].rstrip('/') or '/'
        try:
            handler = self._resolve(method, route)
            return handler(self._decode_body(body), route)
        except ApiError as error:
            return ApiResponse(
                error.status,
                {'error': error.message, 'code': error.code})

    # -- routing -----------------------------------------------------------

    def _resolve(self, method, route):
        """Return the handler for ``(method, route)`` or raise 404/405."""
        table = {
            ('GET', '/'): self._health,
            ('GET', '/health'): self._health,
            ('GET', '/model'): self._get_model,
            ('GET', '/versions'): self._get_versions,
            ('POST', '/stage'): self._stage,
            ('POST', '/validate'): self._validate,
            ('POST', '/apply'): self._apply,
            ('POST', '/rollback'): self._rollback,
        }
        handler = table.get((method, route))
        if handler is not None:
            return handler
        if route.startswith('/versions/'):
            if method != 'GET':
                raise ApiError(405, 'METHOD_NOT_ALLOWED',
                               'method %s not allowed on %s' % (method, route))
            return self._get_version
        # Distinguish "wrong method on a real route" from "no such route".
        if route in {known_route for (_, known_route) in table}:
            raise ApiError(405, 'METHOD_NOT_ALLOWED',
                           'method %s not allowed on %s' % (method, route))
        raise ApiError(404, 'NOT_FOUND', 'no such route: %s' % route)

    @staticmethod
    def _decode_body(body):
        """Parse a JSON request body, tolerating an empty payload."""
        if body is None:
            return {}
        if isinstance(body, (bytes, bytearray)):
            body = body.decode('utf-8')
        body = body.strip()
        if not body:
            return {}
        try:
            data = json.loads(body)
        except ValueError as exc:
            raise ApiError(400, 'BAD_JSON', 'invalid JSON body: %s' % exc)
        if not isinstance(data, dict):
            raise ApiError(400, 'BAD_JSON', 'request body must be a JSON object')
        return data

    @staticmethod
    def _operations(data):
        """Build the operation list from a request body's ``operations``."""
        if 'operations' not in data:
            raise ApiError(400, 'MISSING_OPERATIONS',
                           "request body must contain 'operations'")
        raw = data['operations']
        if not isinstance(raw, list):
            raise ApiError(400, 'BAD_OPERATIONS', "'operations' must be a list")
        try:
            return operations_from_dicts(raw)
        except EditError as exc:
            raise ApiError(400, 'BAD_OPERATIONS', str(exc))

    # -- handlers ----------------------------------------------------------

    def _health(self, data, route):
        """Report liveness and a little model summary."""
        with self._lock:
            version = self._coordinator.current_version
            return ApiResponse(200, {
                'status': 'ok',
                'robot': version.model.name,
                'version': version.index,
                'versions': len(self._coordinator.store),
            })

    def _get_model(self, data, route):
        """Return the current model, its version, and its validation."""
        with self._lock:
            version = self._coordinator.current_version
            return ApiResponse(200, {
                'version': _version_dict(version),
                'urdf': self._coordinator.current_urdf(),
                'validation': self._coordinator.validate_current().to_dict(),
            })

    def _get_versions(self, data, route):
        """Return the full audit log, one entry per version."""
        with self._lock:
            return ApiResponse(200, {
                'versions': self._coordinator.audit_log(),
            })

    def _get_version(self, data, route):
        """Return a single version's snapshot by index."""
        index = self._parse_index(route.rsplit('/', 1)[1])
        with self._lock:
            try:
                version = self._coordinator.store.get(index)
            except IndexError:
                raise ApiError(404, 'NO_SUCH_VERSION',
                               'no version with index %d' % index)
            return ApiResponse(200, {
                'version': _version_dict(version),
                'urdf': version.to_urdf(),
            })

    def _stage(self, data, route):
        """Stage and validate a candidate without committing it."""
        operations = self._operations(data)
        with self._lock:
            staged = self._coordinator.stage(operations)
            candidate_urdf = (
                staged.candidate.to_string()
                if staged.candidate is not None else None)
            body = {
                'is_valid': staged.is_valid,
                'validation': staged.result.to_dict(),
                'urdf': candidate_urdf,
                'error': staged.error,
            }
            self._hub.publish({
                'type': 'staged',
                'is_valid': staged.is_valid,
                'validation': staged.result.to_dict(),
                'error': staged.error,
            })
        return ApiResponse(200, body)

    def _validate(self, data, route):
        """Validate raw URDF, a candidate edit, or the current model."""
        with self._lock:
            if 'urdf' in data:
                if not isinstance(data['urdf'], str):
                    raise ApiError(400, 'BAD_URDF', "'urdf' must be a string")
                _, result = validate_urdf_string(data['urdf'])
                error = None
            elif 'operations' in data:
                operations = self._operations(data)
                staged = self._coordinator.stage(operations)
                result = staged.result
                error = staged.error
            else:
                result = self._coordinator.validate_current()
                error = None
            body = {
                'is_valid': result.is_valid,
                'validation': result.to_dict(),
                'error': error,
            }
            self._hub.publish({
                'type': 'validated',
                'is_valid': result.is_valid,
                'validation': result.to_dict(),
                'error': error,
            })
        return ApiResponse(200, body)

    def _apply(self, data, route):
        """Stage, validate, and commit an edit; reject with 422 on failure."""
        operations = self._operations(data)
        label = data.get('label')
        with self._lock:
            result = self._coordinator.apply(operations, label=label)
            if not result.applied:
                self._hub.publish({
                    'type': 'rejected',
                    'validation': result.result.to_dict(),
                    'error': result.error,
                })
                return ApiResponse(422, {
                    'applied': False,
                    'validation': result.result.to_dict(),
                    'error': result.error,
                })
            diff = self._coordinator.audit_log()[-1]['diff']
            new_urdf = self._coordinator.current_urdf()
            self._hub.publish({
                'type': 'applied',
                'version': _version_dict(result.version),
                'validation': result.result.to_dict(),
                'diff': diff,
            })
        self._notify_commit(new_urdf)
        return ApiResponse(200, {
            'applied': True,
            'version': _version_dict(result.version),
            'validation': result.result.to_dict(),
            'diff': diff,
        })

    def _rollback(self, data, route):
        """Roll back to an earlier version, appending it as the new current."""
        if 'target_index' not in data:
            raise ApiError(400, 'MISSING_TARGET',
                           "request body must contain 'target_index'")
        index = self._parse_index(data['target_index'])
        with self._lock:
            try:
                version = self._coordinator.rollback(index)
            except IndexError:
                raise ApiError(404, 'NO_SUCH_VERSION',
                               'no version with index %d' % index)
            new_urdf = self._coordinator.current_urdf()
            self._hub.publish({
                'type': 'rolled_back',
                'version': _version_dict(version),
                'target_index': index,
            })
        self._notify_commit(new_urdf)
        return ApiResponse(200, {
            'version': _version_dict(version),
            'urdf': new_urdf,
        })

    # -- helpers -----------------------------------------------------------

    def _notify_commit(self, urdf):
        """Run the ``on_commit`` callback (outside the lock) if one is set."""
        if self._on_commit is not None:
            self._on_commit(urdf)

    @staticmethod
    def _parse_index(value):
        """Coerce ``value`` to a non-negative int index or raise 400."""
        try:
            index = int(value)
        except (TypeError, ValueError):
            raise ApiError(400, 'BAD_INDEX',
                           'version index must be an integer, got %r' % (value,))
        if index < 0:
            raise ApiError(400, 'BAD_INDEX',
                           'version index must be non-negative, got %d' % index)
        return index
