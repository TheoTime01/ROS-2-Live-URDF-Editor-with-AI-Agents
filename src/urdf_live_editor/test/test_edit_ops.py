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

"""Unit tests for edit operations and their apply semantics."""

import pytest

from urdf_live_editor.model import edit_ops as ops
from urdf_live_editor.model.robot_model import RobotModel

BASE = ('<robot name="r"><link name="a"/><link name="b"/>'
        '<joint name="j" type="fixed">'
        '<parent link="a"/><child link="b"/></joint></robot>')


def _base():
    """Return a fresh two-link base model."""
    return RobotModel.from_string(BASE)


def test_add_link_returns_new_model():
    """Adding a link returns a new model, leaving the input untouched."""
    model = _base()
    result = ops.AddLink('c').apply(model)
    assert 'c' in result.links
    assert 'c' not in model.links


def test_add_duplicate_link_raises():
    """Adding an existing link name raises EditError."""
    with pytest.raises(ops.EditError):
        ops.AddLink('a').apply(_base())


def test_add_joint_builds_limit():
    """Adding a joint composes its limit from the limit fields."""
    result = ops.AddJoint(
        'k', 'revolute', 'a', 'b', axis=(0, 0, 1),
        lower=-1.0, upper=1.0, effort=5.0, velocity=1.0).apply(_base())
    joint = result.get_joint('k')
    assert joint.axis == (0.0, 0.0, 1.0)
    assert joint.limit.upper == 1.0


def test_remove_joint():
    """Removing a joint deletes it from the model."""
    result = ops.RemoveJoint('j').apply(_base())
    assert 'j' not in result.joints


def test_remove_unknown_joint_raises():
    """Removing a missing joint raises EditError."""
    with pytest.raises(ops.EditError):
        ops.RemoveJoint('nope').apply(_base())


def test_update_joint_changes_fields():
    """Updating a joint mutates only the requested scalar fields."""
    result = ops.UpdateJoint('j', {'joint_type': 'continuous'}).apply(_base())
    assert result.get_joint('j').joint_type == 'continuous'


def test_update_joint_rejects_unknown_field():
    """Updating a joint rejects fields outside the allowed set."""
    with pytest.raises(ops.EditError):
        ops.UpdateJoint('j', {'bogus': 1}).apply(_base())


def test_set_joint_axis_and_limit():
    """Setting the axis and limit updates the joint in place."""
    model = ops.SetJointAxis('j', (1, 0, 0)).apply(_base())
    model = ops.SetJointLimit('j', -2.0, 2.0, 3.0, 4.0).apply(model)
    joint = model.get_joint('j')
    assert joint.axis == (1.0, 0.0, 0.0)
    assert joint.limit.velocity == 4.0


def test_rename_link_updates_joint_references():
    """Renaming a link repoints joints that referenced it."""
    result = ops.Rename('a', 'base').apply(_base())
    assert 'base' in result.links
    assert result.get_joint('j').parent == 'base'


def test_rename_joint():
    """Renaming a joint moves it under the new key."""
    result = ops.Rename('j', 'weld').apply(_base())
    assert 'weld' in result.joints
    assert 'j' not in result.joints


def test_rename_ambiguous_requires_kind():
    """A name shared by a link and a joint requires an explicit kind."""
    model = ops.AddLink('shared').apply(_base())
    model = ops.AddJoint('shared', 'fixed', 'a', 'shared').apply(model)
    with pytest.raises(ops.EditError):
        ops.Rename('shared', 'other').apply(model)


def test_apply_operations_sequence():
    """apply_operations threads a model through several operations."""
    result = ops.apply_operations(_base(), [
        ops.AddLink('c'),
        ops.AddJoint('k', 'fixed', 'b', 'c')])
    assert 'c' in result.links
    assert 'k' in result.joints


def test_operation_roundtrips_through_dict():
    """to_dict/operation_from_dict reconstruct an equivalent operation."""
    original = ops.AddJoint('k', 'revolute', 'a', 'b', axis=(0, 0, 1))
    rebuilt = ops.operation_from_dict(original.to_dict())
    assert rebuilt == original


def test_operation_from_dict_unknown_op_raises():
    """An unknown op tag raises EditError."""
    with pytest.raises(ops.EditError):
        ops.operation_from_dict({'op': 'teleport', 'name': 'x'})
