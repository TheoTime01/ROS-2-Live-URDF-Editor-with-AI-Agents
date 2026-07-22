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

"""Unit tests for the schema validation check."""

from urdf_live_editor.model.robot_model import RobotModel
from urdf_live_editor.validation import schema


def _model(xml):
    """Parse a URDF string into a model."""
    return RobotModel.from_string(xml)


def test_well_formed_accepts_valid_robot():
    """A well-formed <robot> document passes the well-formedness gate."""
    result = schema.check_well_formed('<robot name="r"><link name="a"/></robot>')
    assert result.is_valid


def test_well_formed_rejects_malformed_xml():
    """Malformed XML is reported as SCHEMA_MALFORMED_XML."""
    result = schema.check_well_formed('<robot><link nope</robot>')
    assert not result.is_valid
    assert result.has_code('SCHEMA_MALFORMED_XML')


def test_well_formed_rejects_wrong_root():
    """A non-<robot> root is reported as SCHEMA_ROOT_NOT_ROBOT."""
    result = schema.check_well_formed('<scene/>')
    assert result.has_code('SCHEMA_ROOT_NOT_ROBOT')


def test_duplicate_link_names_flagged():
    """A repeated link name yields SCHEMA_DUPLICATE_LINK."""
    result = schema.check(_model(
        '<robot name="r"><link name="a"/><link name="a"/></robot>'))
    assert result.has_code('SCHEMA_DUPLICATE_LINK')


def test_unknown_parent_reference_flagged():
    """A joint parent that names no link yields SCHEMA_JOINT_UNKNOWN_PARENT."""
    result = schema.check(_model(
        '<robot name="r"><link name="a"/>'
        '<joint name="j" type="fixed">'
        '<parent link="ghost"/><child link="a"/></joint></robot>'))
    assert result.has_code('SCHEMA_JOINT_UNKNOWN_PARENT')


def test_missing_type_flagged():
    """A joint without a type yields SCHEMA_JOINT_MISSING_TYPE."""
    result = schema.check(_model(
        '<robot name="r"><link name="a"/><link name="b"/>'
        '<joint name="j"><parent link="a"/><child link="b"/></joint></robot>'))
    assert result.has_code('SCHEMA_JOINT_MISSING_TYPE')


def test_self_loop_flagged():
    """A joint whose parent equals its child yields SCHEMA_JOINT_SELF_LOOP."""
    result = schema.check(_model(
        '<robot name="r"><link name="a"/>'
        '<joint name="j" type="fixed">'
        '<parent link="a"/><child link="a"/></joint></robot>'))
    assert result.has_code('SCHEMA_JOINT_SELF_LOOP')


def test_valid_model_has_no_schema_issues():
    """A clean two-link model produces no schema issues."""
    result = schema.check(_model(
        '<robot name="r"><link name="a"/><link name="b"/>'
        '<joint name="j" type="fixed">'
        '<parent link="a"/><child link="b"/></joint></robot>'))
    assert result.is_valid
