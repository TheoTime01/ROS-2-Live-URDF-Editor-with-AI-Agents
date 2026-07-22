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
Schema/structure validation for URDF models.

Two layers live here:

* :func:`check_well_formed` operates on a raw string and confirms the document
  parses as XML rooted at ``<robot>``. It is the gate before a model can even
  be built.
* :func:`check` operates on a parsed :class:`RobotModel` and confirms that link
  and joint names are present and unique and that every joint references links
  that actually exist.
"""

import xml.etree.ElementTree as ET

from urdf_live_editor.validation.result import ValidationResult


def check_well_formed(xml_str):
    """Return a result asserting ``xml_str`` is XML rooted at ``<robot>``."""
    result = ValidationResult.ok()
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as exc:
        return result.add_error(
            'SCHEMA_MALFORMED_XML', 'document is not well-formed XML: %s' % exc)
    if root.tag != 'robot':
        result.add_error(
            'SCHEMA_ROOT_NOT_ROBOT',
            'root element is <%s>, expected <robot>' % root.tag)
    return result


def check(model):
    """Validate names and parent/child references of ``model``."""
    result = ValidationResult.ok()
    _check_names(model, result)
    _check_references(model, result)
    return result


def _check_names(model, result):
    """Flag missing or duplicated link and joint names."""
    if '' in model.links:
        result.add_error(
            'SCHEMA_LINK_MISSING_NAME', 'a link has no name attribute')
    if '' in model.joints:
        result.add_error(
            'SCHEMA_JOINT_MISSING_NAME', 'a joint has no name attribute')
    for name in dict.fromkeys(model.duplicate_links):
        result.add_error(
            'SCHEMA_DUPLICATE_LINK',
            'link name is declared more than once', subject=name)
    for name in dict.fromkeys(model.duplicate_joints):
        result.add_error(
            'SCHEMA_DUPLICATE_JOINT',
            'joint name is declared more than once', subject=name)


def _check_references(model, result):
    """Flag joints missing fields or referencing unknown links."""
    for joint in model.joints.values():
        if not joint.joint_type:
            result.add_error(
                'SCHEMA_JOINT_MISSING_TYPE',
                'joint has no type attribute', subject=joint.name)
        _check_endpoint(model, result, joint, joint.parent, 'parent')
        _check_endpoint(model, result, joint, joint.child, 'child')
        if joint.parent and joint.child and joint.parent == joint.child:
            result.add_error(
                'SCHEMA_JOINT_SELF_LOOP',
                'joint connects a link to itself', subject=joint.name)


def _check_endpoint(model, result, joint, link_name, role):
    """Flag a missing or dangling parent/child reference on ``joint``."""
    if not link_name:
        result.add_error(
            'SCHEMA_JOINT_MISSING_%s' % role.upper(),
            'joint has no %s link' % role, subject=joint.name)
    elif link_name not in model.links:
        result.add_error(
            'SCHEMA_JOINT_UNKNOWN_%s' % role.upper(),
            "joint %s link '%s' is not a declared link" % (role, link_name),
            subject=joint.name)
