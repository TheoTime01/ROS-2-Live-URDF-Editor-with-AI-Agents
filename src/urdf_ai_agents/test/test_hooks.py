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
Tests for the pre-tool mutation guard and the post-tool audit trail.

These pin the two guarantees the hooks give the AI layer: a commit can only ever
land a candidate that was staged and validated first, and every applied edit
leaves a reconstructable diff in the audit log.
"""

from urdf_ai_agents.hooks import AuditTrail, MutationGuard
from urdf_ai_agents.tools.schemas import SPEC_BY_NAME
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
APPLY_SPEC = SPEC_BY_NAME['apply_model']
ROLLBACK_SPEC = SPEC_BY_NAME['rollback']
READ_SPEC = SPEC_BY_NAME['read_urdf']


def _box():
    """Return a toolbox seeded with the valid model."""
    return UrdfToolbox.from_urdf(VALID)


def test_guard_allows_read_tools():
    """A read-only tool is never gated."""
    decision = MutationGuard().check(READ_SPEC, {}, _box())
    assert decision.allowed


def test_guard_blocks_apply_without_stage():
    """apply_model with no prior stage is blocked."""
    decision = MutationGuard().check(
        APPLY_SPEC, {'operations': ADD}, _box())
    assert not decision.allowed
    assert 'stage_edit' in decision.reason


def test_guard_blocks_apply_of_unstaged_operations():
    """apply_model whose operations differ from the staged ones is blocked."""
    box = _box()
    box.stage_edit(ADD)
    other = [{'op': 'add_link', 'name': 'different'}]
    decision = MutationGuard().check(
        APPLY_SPEC, {'operations': other}, box)
    assert not decision.allowed
    assert 'match' in decision.reason


def test_guard_blocks_apply_of_invalid_candidate():
    """apply_model is blocked when the staged candidate failed validation."""
    box = _box()
    bad = [{'op': 'remove_link', 'name': 'base'}]
    box.stage_edit(bad)
    decision = MutationGuard().check(
        APPLY_SPEC, {'operations': bad}, box)
    assert not decision.allowed
    assert 'validation' in decision.reason


def test_guard_allows_apply_of_staged_valid_candidate():
    """apply_model matching a valid staged candidate is allowed."""
    box = _box()
    box.stage_edit(ADD)
    decision = MutationGuard().check(APPLY_SPEC, {'operations': ADD}, box)
    assert decision.allowed


def test_guard_allows_rollback_without_stage():
    """Rollback targets an already-validated version, so it needs no stage."""
    decision = MutationGuard().check(
        ROLLBACK_SPEC, {'target_index': 0}, _box())
    assert decision.allowed


def test_audit_records_applied_diff():
    """The audit trail captures the version and diff of an applied edit."""
    box = _box()
    audit = AuditTrail()
    box.stage_edit(ADD)
    status, body = box.apply_model(ADD)
    audit.record('apply_model', {'operations': ADD}, status, body)
    applied = audit.applied_entries()
    assert len(applied) == 1
    assert applied[0].version == 1
    assert applied[0].diff['added_links'] == ['l2']


def test_audit_records_blocked_calls():
    """A blocked call is logged with its reason and no status."""
    audit = AuditTrail()
    audit.record_blocked('apply_model', {'operations': ADD}, 'nope')
    entry = audit.to_list()[0]
    assert entry['blocked'] is True
    assert entry['reason'] == 'nope'
    assert entry['status'] is None
