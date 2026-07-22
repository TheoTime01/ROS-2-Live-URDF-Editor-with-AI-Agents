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

"""Unit tests for the topology validation check."""

from urdf_live_editor.model.robot_model import RobotModel
from urdf_live_editor.validation import topology


def _check(xml):
    """Run the topology check over a URDF string."""
    return topology.check(RobotModel.from_string(xml))


def test_single_chain_is_valid():
    """A simple parent -> child chain forms one valid tree."""
    result = _check(
        '<robot name="r"><link name="a"/><link name="b"/><link name="c"/>'
        '<joint name="j1" type="fixed">'
        '<parent link="a"/><child link="b"/></joint>'
        '<joint name="j2" type="fixed">'
        '<parent link="b"/><child link="c"/></joint></robot>')
    assert result.is_valid


def test_single_link_is_valid():
    """A lone link is a valid single-root tree."""
    assert _check('<robot name="r"><link name="a"/></robot>').is_valid


def test_no_links_flagged():
    """A robot with no links yields TOPO_NO_LINKS."""
    assert _check('<robot name="r"/>').has_code('TOPO_NO_LINKS')


def test_multiple_roots_flagged():
    """Two unconnected links produce TOPO_MULTIPLE_ROOTS."""
    result = _check(
        '<robot name="r"><link name="a"/><link name="b"/></robot>')
    assert result.has_code('TOPO_MULTIPLE_ROOTS')


def test_cycle_flagged():
    """A two-link cycle leaves no root: TOPO_NO_ROOT."""
    result = _check(
        '<robot name="r"><link name="a"/><link name="b"/>'
        '<joint name="j1" type="fixed">'
        '<parent link="a"/><child link="b"/></joint>'
        '<joint name="j2" type="fixed">'
        '<parent link="b"/><child link="a"/></joint></robot>')
    assert result.has_code('TOPO_NO_ROOT')


def test_multiple_parents_flagged():
    """A link that is the child of two joints yields TOPO_MULTIPLE_PARENTS."""
    result = _check(
        '<robot name="r"><link name="a"/><link name="b"/><link name="c"/>'
        '<joint name="j1" type="fixed">'
        '<parent link="a"/><child link="c"/></joint>'
        '<joint name="j2" type="fixed">'
        '<parent link="b"/><child link="c"/></joint></robot>')
    assert result.has_code('TOPO_MULTIPLE_PARENTS')


def test_disconnected_cycle_flagged():
    """A cycle disjoint from the root is reported as disconnected."""
    result = _check(
        '<robot name="r"><link name="root"/><link name="x"/><link name="y"/>'
        '<joint name="j1" type="fixed">'
        '<parent link="x"/><child link="y"/></joint>'
        '<joint name="j2" type="fixed">'
        '<parent link="y"/><child link="x"/></joint></robot>')
    assert result.has_code('TOPO_DISCONNECTED')
