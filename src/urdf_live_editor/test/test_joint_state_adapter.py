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

"""Unit tests for the deterministic joint-state adapter core."""

import math

from urdf_live_editor.joint_state_adapter_node import (
    ACTUATED_TYPES, clamp, JointStateAdapter, wrap_angle)
from urdf_live_editor.model.robot_model import RobotModel

SAMPLE = """
<robot name="arm">
  <link name="base_link"/>
  <link name="link_1"/>
  <link name="link_2"/>
  <link name="tool"/>
  <joint name="shoulder" type="revolute">
    <parent link="base_link"/>
    <child link="link_1"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.0" upper="1.0" effort="5" velocity="1"/>
  </joint>
  <joint name="slide" type="prismatic">
    <parent link="link_1"/>
    <child link="link_2"/>
    <axis xyz="1 0 0"/>
    <limit lower="0.0" upper="0.5" effort="5" velocity="1"/>
  </joint>
  <joint name="wrist" type="continuous">
    <parent link="link_2"/>
    <child link="tool"/>
    <axis xyz="0 0 1"/>
  </joint>
  <joint name="weld" type="fixed">
    <parent link="base_link"/>
    <child link="tool"/>
  </joint>
</robot>
"""


def _model():
    """Parse the sample URDF into a model."""
    return RobotModel.from_string(SAMPLE)


def test_wrap_angle_maps_into_half_open_interval():
    """Values wrap into (-pi, pi], with -pi mapping to +pi."""
    assert wrap_angle(0.0) == 0.0
    assert math.isclose(wrap_angle(math.pi), math.pi)
    assert math.isclose(wrap_angle(-math.pi), math.pi)
    assert math.isclose(wrap_angle(3.0 * math.pi / 2.0), -math.pi / 2.0)
    assert math.isclose(wrap_angle(2.0 * math.pi), 0.0, abs_tol=1e-9)
    assert math.isclose(wrap_angle(5.0 * math.pi), math.pi)


def test_wrap_angle_handles_non_finite():
    """A non-finite command collapses to zero instead of poisoning state."""
    assert wrap_angle(float('inf')) == 0.0
    assert wrap_angle(float('nan')) == 0.0


def test_clamp_respects_open_bounds():
    """Clamping honors each bound and passes through when unbounded."""
    assert clamp(5.0, 0.0, 1.0) == 1.0
    assert clamp(-5.0, 0.0, 1.0) == 0.0
    assert clamp(0.5, 0.0, 1.0) == 0.5
    assert clamp(9.0, None, None) == 9.0
    assert clamp(-9.0, -2.0, None) == -2.0


def test_only_actuated_joints_are_tracked():
    """Fixed joints expose no DOF and are excluded from the joint set."""
    adapter = JointStateAdapter(_model())
    assert set(adapter.joint_names()) == {'shoulder', 'slide', 'wrist'}
    assert 'weld' not in adapter.joint_names()
    assert all(t in ACTUATED_TYPES
               for t in ('revolute', 'prismatic', 'continuous'))


def test_bounded_joint_command_is_clamped():
    """A revolute command beyond its limit is clamped to the bound."""
    adapter = JointStateAdapter(_model())
    assert adapter.set_position('shoulder', 10.0) == 1.0
    assert adapter.set_position('shoulder', -10.0) == -1.0
    assert adapter.set_position('slide', 0.25) == 0.25
    assert adapter.set_position('slide', 2.0) == 0.5


def test_continuous_joint_command_is_wrapped():
    """A continuous command wraps into (-pi, pi]."""
    adapter = JointStateAdapter(_model())
    assert math.isclose(
        adapter.set_position('wrist', 3.0 * math.pi), math.pi)


def test_unknown_joint_command_raises():
    """Commanding a joint that is not actuated raises KeyError."""
    adapter = JointStateAdapter(_model())
    for name in ('weld', 'does_not_exist'):
        try:
            adapter.set_position(name, 0.0)
            raise AssertionError('expected KeyError for %r' % name)
        except KeyError:
            pass


def test_set_positions_skips_unknown_names():
    """Batch commands apply known joints and ignore the rest."""
    adapter = JointStateAdapter(_model())
    adapter.set_positions({'shoulder': 0.5, 'weld': 9.9, 'ghost': 1.0})
    assert adapter.position('shoulder') == 0.5
    assert adapter.position('weld') is None


def test_joint_state_snapshot_is_ordered():
    """Snapshot returns names and positions in model order."""
    adapter = JointStateAdapter(_model())
    adapter.set_positions({'shoulder': 0.3, 'slide': 0.2, 'wrist': 0.1})
    names, positions = adapter.joint_state()
    assert names == ['shoulder', 'slide', 'wrist']
    assert positions == [0.3, 0.2, 0.1]


def test_model_update_preserves_and_renormalizes_positions():
    """A live edit keeps surviving joints and re-clamps to new limits."""
    adapter = JointStateAdapter(_model())
    adapter.set_position('shoulder', 0.9)
    adapter.set_position('slide', 0.4)

    # Tighten the shoulder limit; drop the prismatic joint entirely.
    tighter = _model()
    tighter.joints['shoulder'].limit.upper = 0.5
    del tighter.joints['slide']
    adapter.set_model(tighter)

    assert 'slide' not in adapter.joint_names()
    # 0.9 was valid before, now exceeds the tightened 0.5 upper bound.
    assert adapter.position('shoulder') == 0.5


def test_new_joint_starts_at_normalized_zero():
    """A joint added by an edit starts at zero within its limits."""
    adapter = JointStateAdapter(RobotModel.from_string(SAMPLE))
    assert adapter.position('shoulder') == 0.0
    assert adapter.position('wrist') == 0.0
