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

"""Unit tests for the in-memory robot model parse/serialize."""

import pytest

from urdf_live_editor.model.robot_model import RobotModel, URDFParseError

SIMPLE = """<robot name="r">
  <link name="base"/>
  <link name="tip"/>
  <joint name="j" type="revolute">
    <parent link="base"/>
    <child link="tip"/>
    <origin xyz="0 0 1" rpy="0 0 0"/>
    <axis xyz="0 0 1"/>
    <limit lower="-1.5" upper="1.5" effort="10" velocity="2"/>
  </joint>
</robot>"""


def test_parse_links_and_joints():
    """Links and joints are parsed with their names and types."""
    model = RobotModel.from_string(SIMPLE)
    assert model.name == 'r'
    assert model.link_names() == ['base', 'tip']
    assert model.joint_names() == ['j']
    joint = model.get_joint('j')
    assert joint.joint_type == 'revolute'
    assert joint.parent == 'base'
    assert joint.child == 'tip'
    assert joint.axis == (0.0, 0.0, 1.0)
    assert joint.limit.lower == -1.5
    assert joint.limit.upper == 1.5


def test_malformed_xml_raises():
    """Non-well-formed XML raises URDFParseError."""
    with pytest.raises(URDFParseError):
        RobotModel.from_string('<robot><link name="a"</robot>')


def test_non_robot_root_raises():
    """A root element other than <robot> raises URDFParseError."""
    with pytest.raises(URDFParseError):
        RobotModel.from_string('<thing/>')


def test_roundtrip_preserves_structure():
    """Serializing then re-parsing preserves links, joints, and limits."""
    model = RobotModel.from_string(SIMPLE)
    reparsed = RobotModel.from_string(model.to_string())
    assert reparsed.link_names() == model.link_names()
    assert reparsed.joint_names() == model.joint_names()
    joint = reparsed.get_joint('j')
    assert joint.axis == (0.0, 0.0, 1.0)
    assert joint.origin_xyz == (0.0, 0.0, 1.0)
    assert joint.limit.effort == 10.0


def test_copy_is_independent():
    """Mutating a copy does not affect the original model."""
    model = RobotModel.from_string(SIMPLE)
    clone = model.copy()
    clone.get_joint('j').parent = 'changed'
    assert model.get_joint('j').parent == 'base'


def test_duplicate_names_recorded():
    """Duplicate link/joint names are recorded for the schema check."""
    model = RobotModel.from_string(
        '<robot name="r"><link name="a"/><link name="a"/></robot>')
    assert model.duplicate_links == ['a']
