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

"""End-to-end tests for the stage -> validate -> apply/reject pipeline."""

import pytest

from urdf_live_editor.model import edit_ops as ops
from urdf_live_editor.model_update_coordinator_node import (
    ModelUpdateCoordinator)

VALID = ('<robot name="r"><link name="base"/><link name="l1"/>'
         '<joint name="j1" type="revolute">'
         '<parent link="base"/><child link="l1"/>'
         '<axis xyz="0 0 1"/>'
         '<limit lower="-1" upper="1" effort="5" velocity="1"/>'
         '</joint></robot>')


def _coord():
    """Return a coordinator seeded with the valid two-link model."""
    return ModelUpdateCoordinator.from_urdf(VALID)


def test_from_urdf_rejects_invalid_initial():
    """A coordinator refuses to start from an invalid model."""
    with pytest.raises(ValueError):
        ModelUpdateCoordinator.from_urdf(
            '<robot name="r"><link name="a"/><link name="b"/></robot>')


def test_valid_edit_is_applied():
    """A valid edit commits a new version and updates the current model."""
    coord = _coord()
    result = coord.apply([
        ops.AddLink('l2'),
        ops.AddJoint('j2', 'continuous', 'l1', 'l2', axis=(0, 0, 1))])
    assert result.applied
    assert result.version.index == 1
    assert 'l2' in coord.current_model().links


def test_invalid_edit_is_rejected_and_model_unchanged():
    """An edit that breaks validation is rejected; the model is untouched."""
    coord = _coord()
    before = coord.current_model().link_names()
    result = coord.apply([
        ops.AddJoint('j2', 'fixed', 'ghost', 'l1')])
    assert not result.applied
    assert result.result.has_code('SCHEMA_JOINT_UNKNOWN_PARENT')
    assert coord.current_model().link_names() == before
    assert len(coord.store) == 1


def test_edit_error_is_rejected_without_crash():
    """An impossible operation is reported as an EDIT_ERROR rejection."""
    coord = _coord()
    result = coord.apply([ops.RemoveJoint('does_not_exist')])
    assert not result.applied
    assert result.result.has_code('EDIT_ERROR')


def test_stage_does_not_commit():
    """Staging validates a candidate without recording a version."""
    coord = _coord()
    staged = coord.stage([
        ops.AddLink('l2'),
        ops.AddJoint('j2', 'continuous', 'l1', 'l2', axis=(0, 0, 1))])
    assert staged.is_valid
    assert len(coord.store) == 1


def test_scripted_sequence_stage_apply_rollback():
    """A scripted edit/rollback sequence lands in the expected state."""
    coord = _coord()
    coord.apply([ops.AddLink('l2'),
                 ops.AddJoint('j2', 'continuous', 'l1', 'l2', axis=(0, 0, 1))])
    coord.apply([ops.SetJointLimit('j1', -2.0, 2.0, 8.0, 2.0)])
    assert coord.current_model().get_joint('j1').limit.upper == 2.0

    coord.rollback(0)
    current = coord.current_model()
    assert current.link_names() == ['base', 'l1']
    assert current.get_joint('j1').limit.upper == 1.0
    assert len(coord.store) == 4
    assert coord.validate_current().is_valid


def test_audit_log_tracks_applied_operations():
    """Applied operations are recorded in the audit log."""
    coord = _coord()
    coord.apply([
        ops.AddLink('l2'),
        ops.AddJoint('j2', 'continuous', 'l1', 'l2', axis=(0, 0, 1))])
    log = coord.audit_log()
    assert log[1]['operations'][0]['op'] == 'add_link'
    assert log[1]['diff']['added_links'] == ['l2']
