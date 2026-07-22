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
In-memory representation of a URDF robot model.

The deterministic core operates on a :class:`RobotModel` rather than on raw
XML: links and joints are structured objects, edits produce new models, and
validation reads the same structure. A model can be parsed from a URDF string
and serialized back to one, so it round-trips through the ROS
``robot_description`` parameter. Xacro expansion happens upstream in
``urdf_source_node``; this module only ever sees plain URDF.
"""

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

Vec3 = Tuple[float, float, float]


class URDFParseError(Exception):
    """Raised when a URDF string is not well-formed XML rooted at ``robot``."""


def _parse_vec3(text):
    """Parse a whitespace-separated triple of floats, or ``None`` on failure."""
    if text is None:
        return None
    parts = text.split()
    if len(parts) != 3:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]))
    except ValueError:
        return None


def _parse_float(text):
    """Parse a single float, or ``None`` when absent/unparseable."""
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_num(value):
    """Render a float without gratuitous precision loss."""
    if value == int(value):
        return str(int(value))
    return repr(value)


def _fmt_vec3(vec):
    """Render a 3-vector as a space-separated string."""
    return ' '.join(_fmt_num(v) for v in vec)


@dataclass
class Link:
    """A rigid body. Extra child elements are preserved for round-tripping."""

    name: str
    elements: List[ET.Element] = field(default_factory=list)

    def copy(self):
        """Return a deep copy of this link."""
        return Link(self.name, [copy.deepcopy(e) for e in self.elements])


@dataclass
class JointLimit:
    """Numeric limits for a bounded joint (``None`` means unspecified)."""

    lower: Optional[float] = None
    upper: Optional[float] = None
    effort: Optional[float] = None
    velocity: Optional[float] = None

    def is_empty(self):
        """Return ``True`` when no field is set."""
        return all(v is None for v in (
            self.lower, self.upper, self.effort, self.velocity))

    def copy(self):
        """Return a copy of this limit."""
        return JointLimit(self.lower, self.upper, self.effort, self.velocity)


@dataclass
class Joint:
    """A joint connecting a parent link to a child link."""

    name: str
    joint_type: str
    parent: str
    child: str
    axis: Optional[Vec3] = None
    origin_xyz: Optional[Vec3] = None
    origin_rpy: Optional[Vec3] = None
    limit: Optional[JointLimit] = None

    def copy(self):
        """Return a deep copy of this joint."""
        return Joint(
            self.name, self.joint_type, self.parent, self.child,
            self.axis, self.origin_xyz, self.origin_rpy,
            self.limit.copy() if self.limit is not None else None)


@dataclass
class RobotModel:
    """A whole robot: named links and joints, with parse/serialize support."""

    name: str = 'robot'
    links: Dict[str, Link] = field(default_factory=dict)
    joints: Dict[str, Joint] = field(default_factory=dict)
    # Names that appeared more than once in the source XML. Populated only by
    # :meth:`from_string`; programmatic edits cannot produce duplicates.
    duplicate_links: List[str] = field(default_factory=list)
    duplicate_joints: List[str] = field(default_factory=list)

    def link_names(self):
        """Return the link names in insertion order."""
        return list(self.links.keys())

    def joint_names(self):
        """Return the joint names in insertion order."""
        return list(self.joints.keys())

    def get_link(self, name):
        """Return the named link, or ``None``."""
        return self.links.get(name)

    def get_joint(self, name):
        """Return the named joint, or ``None``."""
        return self.joints.get(name)

    def copy(self):
        """Return a deep, independent copy of this model."""
        clone = RobotModel(name=self.name)
        for link in self.links.values():
            clone.links[link.name] = link.copy()
        for joint in self.joints.values():
            clone.joints[joint.name] = joint.copy()
        return clone

    @classmethod
    def from_string(cls, xml_str):
        """Build a model from a URDF string, raising ``URDFParseError``."""
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError as exc:
            raise URDFParseError('malformed XML: %s' % exc) from exc
        if root.tag != 'robot':
            raise URDFParseError(
                'root element is <%s>, expected <robot>' % root.tag)

        model = cls(name=root.get('name') or 'robot')
        for element in root.findall('link'):
            link = Link(element.get('name') or '')
            link.elements = [copy.deepcopy(child) for child in element]
            if link.name in model.links:
                model.duplicate_links.append(link.name)
            model.links[link.name] = link
        for element in root.findall('joint'):
            joint = cls._joint_from_element(element)
            if joint.name in model.joints:
                model.duplicate_joints.append(joint.name)
            model.joints[joint.name] = joint
        return model

    @staticmethod
    def _joint_from_element(element):
        """Build a :class:`Joint` from a ``<joint>`` XML element."""
        name = element.get('name') or ''
        joint_type = element.get('type') or ''
        parent_el = element.find('parent')
        child_el = element.find('child')
        parent = parent_el.get('link') or '' if parent_el is not None else ''
        child = child_el.get('link') or '' if child_el is not None else ''

        axis = None
        axis_el = element.find('axis')
        if axis_el is not None:
            axis = _parse_vec3(axis_el.get('xyz'))

        origin_xyz = origin_rpy = None
        origin_el = element.find('origin')
        if origin_el is not None:
            origin_xyz = _parse_vec3(origin_el.get('xyz'))
            origin_rpy = _parse_vec3(origin_el.get('rpy'))

        limit = None
        limit_el = element.find('limit')
        if limit_el is not None:
            limit = JointLimit(
                lower=_parse_float(limit_el.get('lower')),
                upper=_parse_float(limit_el.get('upper')),
                effort=_parse_float(limit_el.get('effort')),
                velocity=_parse_float(limit_el.get('velocity')))
        return Joint(
            name, joint_type, parent, child,
            axis=axis, origin_xyz=origin_xyz, origin_rpy=origin_rpy,
            limit=limit)

    def to_element(self):
        """Serialize this model to a ``<robot>`` XML element."""
        root = ET.Element('robot', {'name': self.name})
        for link in self.links.values():
            link_el = ET.SubElement(root, 'link', {'name': link.name})
            for extra in link.elements:
                link_el.append(copy.deepcopy(extra))
        for joint in self.joints.values():
            self._joint_to_element(root, joint)
        return root

    @staticmethod
    def _joint_to_element(root, joint):
        """Append a ``<joint>`` element for ``joint`` under ``root``."""
        attrs = {'name': joint.name}
        if joint.joint_type:
            attrs['type'] = joint.joint_type
        joint_el = ET.SubElement(root, 'joint', attrs)
        ET.SubElement(joint_el, 'parent', {'link': joint.parent})
        ET.SubElement(joint_el, 'child', {'link': joint.child})
        if joint.origin_xyz is not None or joint.origin_rpy is not None:
            origin_attrs = {}
            if joint.origin_xyz is not None:
                origin_attrs['xyz'] = _fmt_vec3(joint.origin_xyz)
            if joint.origin_rpy is not None:
                origin_attrs['rpy'] = _fmt_vec3(joint.origin_rpy)
            ET.SubElement(joint_el, 'origin', origin_attrs)
        if joint.axis is not None:
            ET.SubElement(joint_el, 'axis', {'xyz': _fmt_vec3(joint.axis)})
        if joint.limit is not None and not joint.limit.is_empty():
            limit_attrs = {}
            for key in ('lower', 'upper', 'effort', 'velocity'):
                value = getattr(joint.limit, key)
                if value is not None:
                    limit_attrs[key] = _fmt_num(value)
            ET.SubElement(joint_el, 'limit', limit_attrs)

    def to_string(self):
        """Serialize this model to a pretty-printed URDF string."""
        root = self.to_element()
        ET.indent(root)
        return ET.tostring(root, encoding='unicode')
