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

"""Unit tests for the per-joint-type validation rules."""

from urdf_live_editor.model.robot_model import (
    Joint, JointLimit, Link, RobotModel)
from urdf_live_editor.validation import joint_rules


def _model_with(joint):
    """Return a two-link model wrapping a single ``joint``."""
    model = RobotModel(name='r')
    model.links['a'] = Link('a')
    model.links['b'] = Link('b')
    model.joints[joint.name] = joint
    return model


def _check(joint):
    """Run the joint-rule check over a model containing ``joint``."""
    return joint_rules.check(_model_with(joint))


def test_valid_revolute_passes():
    """A revolute joint with axis and full limits passes."""
    joint = Joint('j', 'revolute', 'a', 'b', axis=(0, 0, 1),
                  limit=JointLimit(-1.0, 1.0, 5.0, 1.0))
    assert _check(joint).is_valid


def test_unknown_type_flagged():
    """An unrecognized joint type yields JOINT_UNKNOWN_TYPE."""
    joint = Joint('j', 'wobble', 'a', 'b')
    assert _check(joint).has_code('JOINT_UNKNOWN_TYPE')


def test_revolute_missing_axis_flagged():
    """A revolute joint without an axis yields JOINT_MISSING_AXIS."""
    joint = Joint('j', 'revolute', 'a', 'b',
                  limit=JointLimit(-1.0, 1.0, 5.0, 1.0))
    assert _check(joint).has_code('JOINT_MISSING_AXIS')


def test_zero_axis_flagged():
    """A zero axis vector yields JOINT_ZERO_AXIS."""
    joint = Joint('j', 'continuous', 'a', 'b', axis=(0, 0, 0),
                  limit=JointLimit(effort=5.0, velocity=1.0))
    assert _check(joint).has_code('JOINT_ZERO_AXIS')


def test_revolute_missing_limit_flagged():
    """A revolute joint with no limit yields JOINT_MISSING_LIMIT."""
    joint = Joint('j', 'revolute', 'a', 'b', axis=(0, 0, 1))
    assert _check(joint).has_code('JOINT_MISSING_LIMIT')


def test_inverted_limit_flagged():
    """A lower bound above the upper bound yields JOINT_LIMIT_INVERTED."""
    joint = Joint('j', 'prismatic', 'a', 'b', axis=(1, 0, 0),
                  limit=JointLimit(1.0, -1.0, 5.0, 1.0))
    assert _check(joint).has_code('JOINT_LIMIT_INVERTED')


def test_nonpositive_effort_flagged():
    """A non-positive effort limit yields JOINT_EFFORT_NONPOSITIVE."""
    joint = Joint('j', 'revolute', 'a', 'b', axis=(0, 0, 1),
                  limit=JointLimit(-1.0, 1.0, 0.0, 1.0))
    assert _check(joint).has_code('JOINT_EFFORT_NONPOSITIVE')


def test_continuous_without_limit_warns_only():
    """A continuous joint missing effort/velocity warns but stays valid."""
    joint = Joint('j', 'continuous', 'a', 'b', axis=(0, 0, 1))
    result = _check(joint)
    assert result.is_valid
    assert result.has_code('JOINT_CONTINUOUS_NO_LIMIT')


def test_fixed_with_axis_warns_only():
    """A fixed joint carrying an axis warns but stays valid."""
    joint = Joint('j', 'fixed', 'a', 'b', axis=(0, 0, 1))
    result = _check(joint)
    assert result.is_valid
    assert result.has_code('JOINT_FIXED_HAS_AXIS')
