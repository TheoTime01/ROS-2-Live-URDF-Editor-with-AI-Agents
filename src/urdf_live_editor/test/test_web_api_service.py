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
Offline contract tests for the transport-agnostic web-API service.

These drive :class:`WebApiService.handle` directly (no sockets, no rclpy) and
pin the request/response contract for every endpoint of the edit flow -- read,
stage, validate, apply, rollback -- plus the event stream the WebSocket layer
broadcasts. They are the Milestone 3 "the same edit flow is drivable through the
API" acceptance proof at the dispatch level; ``test_web_api_server`` proves the
same contract over a real socket.
"""

import json

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


def _service(**kwargs):
    """Return a service seeded with the valid two-link model."""
    return WebApiService.from_urdf(VALID, **kwargs)


def _call(service, method, path, body=None):
    """Invoke ``handle`` and return ``(status, parsed_json_body)``."""
    raw = json.dumps(body).encode('utf-8') if body is not None else b''
    response = service.handle(method, path, raw)
    return response.status, json.loads(response.to_json())


def test_health_reports_ok():
    """GET /health returns liveness and a model summary."""
    status, body = _call(_service(), 'GET', '/health')
    assert status == 200
    assert body['status'] == 'ok'
    assert body['robot'] == 'r'
    assert body['versions'] == 1


def test_get_model_returns_urdf_and_validation():
    """GET /model returns the current version, URDF, and validation."""
    status, body = _call(_service(), 'GET', '/model')
    assert status == 200
    assert body['version']['index'] == 0
    assert '<robot' in body['urdf']
    assert body['validation']['is_valid'] is True


def test_get_versions_lists_history():
    """GET /versions returns one audit entry for the seed version."""
    status, body = _call(_service(), 'GET', '/versions')
    assert status == 200
    assert len(body['versions']) == 1
    assert body['versions'][0]['index'] == 0


def test_get_single_version_and_missing():
    """GET /versions/{i} returns a snapshot, or 404 when absent."""
    service = _service()
    status, body = _call(service, 'GET', '/versions/0')
    assert status == 200
    assert body['version']['index'] == 0
    assert '<robot' in body['urdf']

    status, body = _call(service, 'GET', '/versions/9')
    assert status == 404
    assert body['code'] == 'NO_SUCH_VERSION'


def test_stage_valid_does_not_commit():
    """POST /stage validates a candidate and never records a version."""
    service = _service()
    status, body = _call(service, 'POST', '/stage', {'operations': ADD_L2})
    assert status == 200
    assert body['is_valid'] is True
    assert 'l2' in body['urdf']
    # No commit happened.
    _, versions = _call(service, 'GET', '/versions')
    assert len(versions['versions']) == 1


def test_stage_invalid_reports_diagnostics():
    """POST /stage with a validation-breaking edit stays 200 with issues."""
    ops = [{'op': 'add_joint', 'name': 'jx', 'joint_type': 'fixed',
            'parent': 'ghost', 'child': 'l1'}]
    status, body = _call(_service(), 'POST', '/stage', {'operations': ops})
    assert status == 200
    assert body['is_valid'] is False
    codes = [i['code'] for i in body['validation']['issues']]
    assert 'SCHEMA_JOINT_UNKNOWN_PARENT' in codes


def test_stage_edit_error_is_reported():
    """An impossible operation surfaces as an EDIT_ERROR, not a crash."""
    ops = [{'op': 'remove_joint', 'name': 'nope'}]
    status, body = _call(_service(), 'POST', '/stage', {'operations': ops})
    assert status == 200
    assert body['is_valid'] is False
    assert body['error'] is not None


def test_stage_rejects_bad_operations():
    """Unknown operations are a 400 client error."""
    ops = [{'op': 'no_such_op'}]
    status, body = _call(_service(), 'POST', '/stage', {'operations': ops})
    assert status == 400
    assert body['code'] == 'BAD_OPERATIONS'


def test_stage_requires_operations():
    """A stage body without 'operations' is a 400."""
    status, body = _call(_service(), 'POST', '/stage', {})
    assert status == 400
    assert body['code'] == 'MISSING_OPERATIONS'


def test_validate_current_model():
    """POST /validate with no body validates the current model."""
    status, body = _call(_service(), 'POST', '/validate')
    assert status == 200
    assert body['is_valid'] is True


def test_validate_raw_urdf_string():
    """POST /validate with a raw URDF reports its verdict."""
    broken = '<robot name="r"><link name="a"/><link name="b"/></robot>'
    status, body = _call(_service(), 'POST', '/validate', {'urdf': broken})
    assert status == 200
    assert body['is_valid'] is False


def test_validate_rejects_non_string_urdf():
    """POST /validate with a non-string 'urdf' is a 400, not a crash."""
    status, body = _call(_service(), 'POST', '/validate', {'urdf': 123})
    assert status == 400
    assert body['code'] == 'BAD_URDF'


def test_validate_candidate_operations():
    """POST /validate with operations validates the staged candidate."""
    status, body = _call(_service(), 'POST', '/validate',
                         {'operations': ADD_L2})
    assert status == 200
    assert body['is_valid'] is True


def test_apply_commits_a_new_version():
    """POST /apply commits and reports the new version and diff."""
    committed = []
    service = _service(on_commit=committed.append)
    status, body = _call(service, 'POST', '/apply', {'operations': ADD_L2})
    assert status == 200
    assert body['applied'] is True
    assert body['version']['index'] == 1
    assert body['diff']['added_links'] == ['l2']
    # The commit callback received the new URDF.
    assert committed and '<robot' in committed[0]
    _, model = _call(service, 'GET', '/model')
    assert model['version']['index'] == 1


def test_apply_rejects_invalid_edit_with_422():
    """An edit that fails validation is a 422 and leaves the model intact."""
    ops = [{'op': 'add_joint', 'name': 'jx', 'joint_type': 'fixed',
            'parent': 'ghost', 'child': 'l1'}]
    service = _service()
    status, body = _call(service, 'POST', '/apply', {'operations': ops})
    assert status == 422
    assert body['applied'] is False
    _, versions = _call(service, 'GET', '/versions')
    assert len(versions['versions']) == 1


def test_apply_rejects_bad_operations_with_400():
    """Malformed operations are a 400, distinct from a 422 rejection."""
    ops = [{'op': 'add_joint'}]
    status, body = _call(_service(), 'POST', '/apply', {'operations': ops})
    assert status == 400
    assert body['code'] == 'BAD_OPERATIONS'


def test_rollback_restores_earlier_version():
    """POST /rollback appends a copy of an earlier version as current."""
    service = _service()
    _call(service, 'POST', '/apply', {'operations': ADD_L2})
    status, body = _call(service, 'POST', '/rollback', {'target_index': 0})
    assert status == 200
    assert body['version']['label'] == 'rollback to v0'
    _, model = _call(service, 'GET', '/model')
    assert 'l2' not in model['urdf']


def test_rollback_bad_index_is_404():
    """Rolling back to a non-existent version is a 404."""
    status, body = _call(_service(), 'POST', '/rollback', {'target_index': 7})
    assert status == 404
    assert body['code'] == 'NO_SUCH_VERSION'


def test_rollback_requires_target_index():
    """A rollback body without target_index is a 400."""
    status, body = _call(_service(), 'POST', '/rollback', {})
    assert status == 400
    assert body['code'] == 'MISSING_TARGET'


def test_unknown_route_is_404():
    """An unmapped path is a 404."""
    status, body = _call(_service(), 'GET', '/nope')
    assert status == 404
    assert body['code'] == 'NOT_FOUND'


def test_method_not_allowed_is_405():
    """A known route with the wrong method is a 405."""
    status, body = _call(_service(), 'POST', '/model')
    assert status == 405
    assert body['code'] == 'METHOD_NOT_ALLOWED'


def test_bad_json_body_is_400():
    """A malformed JSON body is a 400."""
    response = _service().handle('POST', '/apply', b'{not json')
    assert response.status == 400
    assert json.loads(response.to_json())['code'] == 'BAD_JSON'


def test_apply_emits_applied_event():
    """Applying an edit publishes an 'applied' event on the hub."""
    service = _service()
    subscription = service.hub.subscribe()
    _call(service, 'POST', '/apply', {'operations': ADD_L2})
    event = subscription.get(timeout=1.0)
    assert event['type'] == 'applied'
    assert event['diff']['added_links'] == ['l2']
    assert 'seq' in event


def test_rollback_emits_rolled_back_event():
    """Rolling back publishes a 'rolled_back' event on the hub."""
    service = _service()
    _call(service, 'POST', '/apply', {'operations': ADD_L2})
    subscription = service.hub.subscribe()
    _call(service, 'POST', '/rollback', {'target_index': 0})
    event = subscription.get(timeout=1.0)
    assert event['type'] == 'rolled_back'
    assert event['target_index'] == 0


def test_snapshot_event_describes_current_model():
    """The snapshot handed to new WebSocket clients holds the live model."""
    snapshot = _service().snapshot_event()
    assert snapshot['type'] == 'snapshot'
    assert snapshot['version']['index'] == 0
    assert '<robot' in snapshot['urdf']
    assert snapshot['validation']['is_valid'] is True
