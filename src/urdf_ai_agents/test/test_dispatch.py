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
Tests for :class:`ToolDispatcher`, the guard-and-audit tool-call runtime.

The dispatcher is the single choke point every caller shares, so these tests
confirm it enforces the guard, records the audit, and reports unknown tools and
malformed arguments cleanly instead of raising.
"""

from urdf_ai_agents.dispatch import ToolDispatcher
from urdf_ai_agents.tools.toolbox import UrdfToolbox

VALID = ('<robot name="r"><link name="base"/><link name="l1"/>'
         '<joint name="j1" type="revolute">'
         '<parent link="base"/><child link="l1"/><axis xyz="0 0 1"/>'
         '<limit lower="-1" upper="1" effort="5" velocity="1"/></joint></robot>')

ADD = [
    {'op': 'add_link', 'name': 'l2'},
    {'op': 'add_joint', 'name': 'j2', 'joint_type': 'fixed',
     'parent': 'l1', 'child': 'l2'},
]


def _dispatcher():
    """Return a dispatcher over the valid model."""
    return ToolDispatcher(UrdfToolbox.from_urdf(VALID))


def test_unknown_tool_is_reported():
    """An unregistered tool name returns an error result, not an exception."""
    result = _dispatcher().call('teleport', {})
    assert result.ok is False
    assert result.data['code'] == 'UNKNOWN_TOOL'


def test_stage_then_apply_succeeds_and_audits():
    """A staged, valid edit applies and both calls are audited."""
    disp = _dispatcher()
    disp.call('stage_edit', {'operations': ADD})
    result = disp.call('apply_model', {'operations': ADD})
    assert result.ok and result.blocked is False
    trail = disp.audit.to_list()
    assert [e['tool'] for e in trail] == ['stage_edit', 'apply_model']
    assert disp.audit.applied_entries()[0].diff['added_links'] == ['l2']


def test_apply_without_stage_is_blocked_and_audited():
    """The dispatcher blocks an unstaged apply and logs the block."""
    disp = _dispatcher()
    result = disp.call('apply_model', {'operations': ADD})
    assert result.blocked is True
    assert result.data['code'] == 'BLOCKED_BY_HOOK'
    assert disp.audit.to_list()[0]['blocked'] is True


def test_tool_error_becomes_400_result():
    """A malformed tool argument surfaces as a 400 result."""
    result = _dispatcher().call('describe_joint', {'name': ''})
    assert result.ok is False
    assert result.status == 400


def test_read_urdf_is_ok():
    """A plain read dispatches to a 200 result."""
    result = _dispatcher().call('read_urdf')
    assert result.ok is True
    assert '<robot' in result.data['urdf']
