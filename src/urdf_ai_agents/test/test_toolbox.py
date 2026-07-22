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
Offline tests for :class:`UrdfToolbox`, the concrete tool implementations.

The toolbox routes every call through the same trusted web-API service the HTTP
layer uses, so these tests double as proof that the AI layer cannot bypass
validation: an invalid apply is refused, and staging records exactly what a
later apply must match.
"""

import pytest

from urdf_ai_agents.tools.toolbox import ToolError, UrdfToolbox

VALID = ('<robot name="arm">'
         '<link name="base"/><link name="link_1"/><link name="link_2"/>'
         '<joint name="shoulder" type="revolute">'
         '<parent link="base"/><child link="link_1"/><axis xyz="0 0 1"/>'
         '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
         '<joint name="j2" type="revolute">'
         '<parent link="link_1"/><child link="link_2"/><axis xyz="0 1 0"/>'
         '<limit lower="-1.5" upper="1.5" effort="10" velocity="1"/></joint>'
         '</robot>')

ADD_L3 = [
    {'op': 'add_link', 'name': 'link_3'},
    {'op': 'add_joint', 'name': 'elbow', 'joint_type': 'revolute',
     'parent': 'link_2', 'child': 'link_3', 'axis': [0, 1, 0],
     'lower': -1.5708, 'upper': 1.5708, 'effort': 10, 'velocity': 1},
]


def _box():
    """Return a toolbox seeded with the valid three-link arm."""
    return UrdfToolbox.from_urdf(VALID)


def test_read_urdf_returns_model_and_validation():
    """read_urdf returns the current URDF and a passing verdict."""
    status, body = _box().read_urdf()
    assert status == 200
    assert '<robot' in body['urdf']
    assert body['validation']['is_valid'] is True


def test_describe_joint_reports_semantics_and_issues():
    """describe_joint returns type semantics and (here) no issues."""
    status, body = _box().describe_joint('shoulder')
    assert status == 200
    assert body['type'] == 'revolute'
    assert body['movable'] is True
    assert body['parent'] == 'base'
    assert 'rotates about its axis' in body['semantics']
    assert body['issues'] == []


def test_describe_joint_unknown_is_404():
    """describe_joint for a missing joint reports 404 and lists joints."""
    status, body = _box().describe_joint('nope')
    assert status == 404
    assert body['code'] == 'NO_SUCH_JOINT'
    assert 'shoulder' in body['joints']


def test_describe_joint_requires_name():
    """A blank joint name is a ToolError, not a crash."""
    with pytest.raises(ToolError):
        _box().describe_joint('')


def test_validate_model_current_and_raw():
    """validate_model checks the current model or a raw URDF string."""
    box = _box()
    status, body = box.validate_model()
    assert status == 200 and body['is_valid'] is True
    broken = '<robot name="r"><link name="a"/><link name="b"/></robot>'
    status, body = box.validate_model(urdf=broken)
    assert status == 200 and body['is_valid'] is False


def test_stage_records_last_staged_candidate():
    """stage_edit remembers the operations signature and validity."""
    box = _box()
    status, body = box.stage_edit(ADD_L3)
    assert status == 200 and body['is_valid'] is True
    assert box.last_staged is not None
    assert box.last_staged['is_valid'] is True


def test_apply_commits_and_clears_staging():
    """apply_model commits a new version and forgets the staged candidate."""
    box = _box()
    box.stage_edit(ADD_L3)
    status, body = box.apply_model(ADD_L3, label='add elbow')
    assert status == 200 and body['applied'] is True
    assert body['version']['index'] == 1
    assert box.last_staged is None
    _, model = box.read_urdf()
    assert 'link_3' in model['urdf']


def test_apply_invalid_edit_is_422_and_leaves_model():
    """An edit that fails validation is refused with 422; model untouched."""
    box = _box()
    bad = [{'op': 'add_joint', 'name': 'jx', 'joint_type': 'revolute',
            'parent': 'ghost', 'child': 'link_2'}]
    box.stage_edit(bad)
    status, body = box.apply_model(bad)
    assert status == 422 and body['applied'] is False
    _, model = box.read_urdf()
    assert model['version']['index'] == 0


def test_rollback_restores_earlier_version():
    """Rollback appends a copy of an earlier version as the new current."""
    box = _box()
    box.stage_edit(ADD_L3)
    box.apply_model(ADD_L3)
    status, body = box.rollback(0)
    assert status == 200
    _, model = box.read_urdf()
    assert 'link_3' not in model['urdf']


def test_from_urdf_can_load_an_invalid_model_for_repair():
    """With require_valid=False a broken model loads for the repair flow."""
    broken = ('<robot name="r"><link name="base"/><link name="l1"/>'
              '<joint name="j1" type="revolute">'
              '<parent link="base"/><child link="l1"/></joint></robot>')
    box = UrdfToolbox.from_urdf(broken, require_valid=False)
    _, model = box.read_urdf()
    assert model['validation']['is_valid'] is False
