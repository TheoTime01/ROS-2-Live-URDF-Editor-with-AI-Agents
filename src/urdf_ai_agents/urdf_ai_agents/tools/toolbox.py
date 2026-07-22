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
Pure-Python implementations of the six URDF tools.

:class:`UrdfToolbox` is the concrete work the MCP tools do. Every method routes
through a :class:`~urdf_live_editor.web.service.WebApiService`, which is the
same trusted front end the HTTP layer uses, so the AI layer travels the exact
stage -> validate -> apply/reject path a human does and can never bypass
validation. There is no ``rclpy`` and no Claude SDK here: the toolbox is fully
exercised offline, and the recorded-response tests drive it directly.

The toolbox also remembers the *last staged candidate* so the mutation guard in
:mod:`urdf_ai_agents.hooks` can enforce that an ``apply_model`` only ever
commits something that was staged and validated first.
"""

import json

from urdf_ai_agents.explanations import describe_joint_report
from urdf_live_editor.web.service import WebApiService


def operations_key(operations):
    """Return a canonical, order-sensitive signature for an operation list."""
    return json.dumps(operations, sort_keys=True, default=list)


class ToolError(Exception):
    """Raised when a tool is called with malformed arguments."""

    def __init__(self, code, message):
        """Record a short machine ``code`` and a human ``message``."""
        super().__init__(message)
        self.code = code
        self.message = message


class UrdfToolbox:
    """Backs the six MCP tools with the trusted deterministic pipeline."""

    def __init__(self, service):
        """Wrap an existing :class:`WebApiService`."""
        self._service = service
        self._last_staged = None

    @classmethod
    def from_urdf(cls, xml_str, require_valid=True, **kwargs):
        """
        Build a toolbox from a URDF string.

        With ``require_valid`` (the default) the model must already validate,
        matching the editing flow. The repair flow passes ``require_valid`` as
        ``False`` so a broken model can be loaded, diagnosed, and fixed.
        """
        if require_valid:
            service = WebApiService.from_urdf(xml_str, **kwargs)
            return cls(service)
        from urdf_live_editor.model.robot_model import RobotModel
        from urdf_live_editor.model_update_coordinator_node import (
            ModelUpdateCoordinator)
        model = RobotModel.from_string(xml_str)
        service = WebApiService(ModelUpdateCoordinator(model), **kwargs)
        return cls(service)

    @property
    def service(self):
        """Return the wrapped web-API service."""
        return self._service

    @property
    def last_staged(self):
        """
        Return a record of the last staged candidate, or ``None``.

        The record is a dict with ``key`` (the operations signature) and
        ``is_valid`` (whether the candidate passed validation).
        """
        return self._last_staged

    # -- tool implementations ---------------------------------------------

    def read_urdf(self):
        """Return the current model, version, and validation verdict."""
        return self._request('GET', '/model')

    def describe_joint(self, name):
        """Describe one joint, its kinematic meaning, and its issues."""
        if not isinstance(name, str) or not name:
            raise ToolError('BAD_NAME', "'name' must be a non-empty string")
        coordinator = self._service.coordinator
        model = coordinator.current_version.model
        joint = model.get_joint(name)
        if joint is None:
            return 404, {
                'error': "no joint named '%s'" % name,
                'code': 'NO_SUCH_JOINT',
                'joints': model.joint_names(),
            }
        issues = [
            issue for issue in coordinator.validate_current()
            if issue.subject == name]
        return 200, describe_joint_report(joint, issues)

    def validate_model(self, urdf=None, operations=None):
        """Validate raw URDF, a candidate edit, or the current model."""
        body = {}
        if urdf is not None:
            body['urdf'] = urdf
        elif operations is not None:
            body['operations'] = operations
        return self._request('POST', '/validate', body)

    def stage_edit(self, operations):
        """Stage and validate a candidate, remembering it for apply_model."""
        self._require_operations(operations)
        status, body = self._request(
            'POST', '/stage', {'operations': operations})
        if status == 200:
            self._last_staged = {
                'key': operations_key(operations),
                'is_valid': bool(body.get('is_valid')),
            }
        return status, body

    def apply_model(self, operations, label=None):
        """Commit a staged candidate; clear the staging record on success."""
        self._require_operations(operations)
        body = {'operations': operations}
        if label is not None:
            body['label'] = label
        status, response = self._request('POST', '/apply', body)
        if status == 200 and response.get('applied'):
            self._last_staged = None
        return status, response

    def rollback(self, target_index):
        """Restore an earlier committed version by index."""
        return self._request(
            'POST', '/rollback', {'target_index': target_index})

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _require_operations(operations):
        """Reject a missing or non-list ``operations`` argument."""
        if not isinstance(operations, list):
            raise ToolError(
                'BAD_OPERATIONS', "'operations' must be a list of edit ops")

    def _request(self, method, path, body=None):
        """Drive the web service and return ``(status, parsed_body)``."""
        raw = json.dumps(body).encode('utf-8') if body is not None else b''
        response = self._service.handle(method, path, raw)
        return response.status, json.loads(response.to_json())
