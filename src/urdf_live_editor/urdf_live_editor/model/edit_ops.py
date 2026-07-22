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
``EditOperation`` types and their ``apply`` semantics.

An :class:`EditOperation` is the unit of change to a model. Each operation is a
small, JSON-serializable value object that knows how to produce a *new* model
with the change applied, leaving the input untouched. Operations enforce only
their own structural preconditions (for example, you cannot add a joint whose
name already exists); whether the *result* is a valid robot is left to the
validation engine. That split is what lets the coordinator stage an edit,
validate the candidate, and apply or reject it without any operation ever
mutating the live model.

The same operation vocabulary is what the AI layer will emit as JSON in a later
milestone, so :func:`operation_from_dict` and ``to_dict`` round-trip every op.
"""

import abc
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from urdf_live_editor.model.robot_model import Joint, JointLimit, Link

Vec3 = Tuple[float, float, float]


class EditError(Exception):
    """Raised when an operation's preconditions are not met."""


class EditOperation(abc.ABC):
    """Base class for a single, reversible unit of model change."""

    op = None

    @abc.abstractmethod
    def apply(self, model):
        """Return a new model with this operation applied to ``model``."""

    def to_dict(self):
        """Return a JSON-serializable representation of this operation."""
        data = {'op': self.op}
        data.update(_dataclass_fields(self))
        return data


@dataclass(frozen=True)
class AddLink(EditOperation):
    """Add a new, empty link."""

    op = 'add_link'
    name: str

    def apply(self, model):
        """Add the link, rejecting an empty or duplicate name."""
        _require_name(self.name, 'link')
        result = model.copy()
        if self.name in result.links:
            raise EditError("link '%s' already exists" % self.name)
        result.links[self.name] = Link(self.name)
        return result


@dataclass(frozen=True)
class RemoveLink(EditOperation):
    """Remove an existing link (dangling joints are left for validation)."""

    op = 'remove_link'
    name: str

    def apply(self, model):
        """Remove the link, rejecting an unknown name."""
        result = model.copy()
        if self.name not in result.links:
            raise EditError("link '%s' does not exist" % self.name)
        del result.links[self.name]
        return result


@dataclass(frozen=True)
class AddJoint(EditOperation):
    """Add a new joint between two links."""

    op = 'add_joint'
    name: str
    joint_type: str
    parent: str
    child: str
    axis: Optional[Vec3] = None
    origin_xyz: Optional[Vec3] = None
    origin_rpy: Optional[Vec3] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    effort: Optional[float] = None
    velocity: Optional[float] = None

    def apply(self, model):
        """Add the joint, rejecting an empty or duplicate name."""
        _require_name(self.name, 'joint')
        result = model.copy()
        if self.name in result.joints:
            raise EditError("joint '%s' already exists" % self.name)
        limit = JointLimit(self.lower, self.upper, self.effort, self.velocity)
        result.joints[self.name] = Joint(
            self.name, self.joint_type, self.parent, self.child,
            axis=_as_vec3(self.axis),
            origin_xyz=_as_vec3(self.origin_xyz),
            origin_rpy=_as_vec3(self.origin_rpy),
            limit=None if limit.is_empty() else limit)
        return result


@dataclass(frozen=True)
class RemoveJoint(EditOperation):
    """Remove an existing joint."""

    op = 'remove_joint'
    name: str

    def apply(self, model):
        """Remove the joint, rejecting an unknown name."""
        result = model.copy()
        if self.name not in result.joints:
            raise EditError("joint '%s' does not exist" % self.name)
        del result.joints[self.name]
        return result


_UPDATABLE_FIELDS = frozenset((
    'joint_type', 'parent', 'child', 'origin_xyz', 'origin_rpy'))


@dataclass(frozen=True)
class UpdateJoint(EditOperation):
    """Update scalar fields of an existing joint (type/parent/child/origin)."""

    op = 'update_joint'
    name: str
    changes: Dict[str, object] = field(default_factory=dict)

    def apply(self, model):
        """Apply the field changes, rejecting unknown joints or fields."""
        result = model.copy()
        joint = result.joints.get(self.name)
        if joint is None:
            raise EditError("joint '%s' does not exist" % self.name)
        unknown = set(self.changes) - _UPDATABLE_FIELDS
        if unknown:
            raise EditError(
                'unknown joint fields: %s' % ', '.join(sorted(unknown)))
        for key, value in self.changes.items():
            if key in ('origin_xyz', 'origin_rpy'):
                value = _as_vec3(value)
            setattr(joint, key, value)
        return result


@dataclass(frozen=True)
class SetJointAxis(EditOperation):
    """Set (or clear) the rotation/translation axis of a joint."""

    op = 'set_joint_axis'
    name: str
    axis: Optional[Vec3] = None

    def apply(self, model):
        """Set the joint axis, rejecting an unknown joint."""
        result = model.copy()
        joint = result.joints.get(self.name)
        if joint is None:
            raise EditError("joint '%s' does not exist" % self.name)
        joint.axis = _as_vec3(self.axis)
        return result


@dataclass(frozen=True)
class SetJointLimit(EditOperation):
    """Set the numeric limits of a joint."""

    op = 'set_joint_limit'
    name: str
    lower: Optional[float] = None
    upper: Optional[float] = None
    effort: Optional[float] = None
    velocity: Optional[float] = None

    def apply(self, model):
        """Set the joint limit, rejecting an unknown joint."""
        result = model.copy()
        joint = result.joints.get(self.name)
        if joint is None:
            raise EditError("joint '%s' does not exist" % self.name)
        limit = JointLimit(self.lower, self.upper, self.effort, self.velocity)
        joint.limit = None if limit.is_empty() else limit
        return result


@dataclass(frozen=True)
class Rename(EditOperation):
    """Rename a link or joint, updating any joint references to a link."""

    op = 'rename'
    old_name: str
    new_name: str
    kind: Optional[str] = None

    def apply(self, model):
        """Rename the target, rejecting collisions or ambiguity."""
        _require_name(self.new_name, self.kind or 'entity')
        result = model.copy()
        kind = self._resolve_kind(result)
        if kind == 'link':
            self._rename_link(result)
        else:
            self._rename_joint(result)
        return result

    def _resolve_kind(self, model):
        """Determine whether the target is a link or a joint."""
        if self.kind in ('link', 'joint'):
            return self.kind
        if self.kind is not None:
            raise EditError("unknown rename kind '%s'" % self.kind)
        is_link = self.old_name in model.links
        is_joint = self.old_name in model.joints
        if is_link and is_joint:
            raise EditError(
                "'%s' names both a link and a joint; specify kind"
                % self.old_name)
        if is_link:
            return 'link'
        if is_joint:
            return 'joint'
        raise EditError("no link or joint named '%s'" % self.old_name)

    def _rename_link(self, model):
        """Rename a link and repoint every joint that referenced it."""
        if self.old_name not in model.links:
            raise EditError("link '%s' does not exist" % self.old_name)
        if self.new_name in model.links:
            raise EditError("link '%s' already exists" % self.new_name)
        model.links = {
            (self.new_name if name == self.old_name else name): link
            for name, link in model.links.items()}
        model.links[self.new_name].name = self.new_name
        for joint in model.joints.values():
            if joint.parent == self.old_name:
                joint.parent = self.new_name
            if joint.child == self.old_name:
                joint.child = self.new_name

    def _rename_joint(self, model):
        """Rename a joint."""
        if self.old_name not in model.joints:
            raise EditError("joint '%s' does not exist" % self.old_name)
        if self.new_name in model.joints:
            raise EditError("joint '%s' already exists" % self.new_name)
        model.joints = {
            (self.new_name if name == self.old_name else name): joint
            for name, joint in model.joints.items()}
        model.joints[self.new_name].name = self.new_name


def apply_operations(model, operations):
    """Apply a sequence of operations, returning the resulting model."""
    result = model
    for operation in operations:
        result = operation.apply(result)
    return result


_REGISTRY = {
    cls.op: cls for cls in (
        AddLink, RemoveLink, AddJoint, RemoveJoint,
        UpdateJoint, SetJointAxis, SetJointLimit, Rename)}


def operation_from_dict(data):
    """Build an :class:`EditOperation` from its dict representation."""
    if 'op' not in data:
        raise EditError("edit operation is missing its 'op' field")
    cls = _REGISTRY.get(data['op'])
    if cls is None:
        raise EditError("unknown edit operation '%s'" % data['op'])
    kwargs = {key: value for key, value in data.items() if key != 'op'}
    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise EditError(
            "invalid fields for operation '%s': %s" % (data['op'], exc))


def operations_from_dicts(items):
    """Build a list of operations from a list of dicts."""
    return [operation_from_dict(item) for item in items]


def _require_name(name, kind):
    """Reject an empty or non-string name for ``kind``."""
    if not isinstance(name, str) or not name:
        raise EditError('%s name must be a non-empty string' % kind)


def _as_vec3(value):
    """Coerce a 3-element sequence to a float tuple, or return ``None``."""
    if value is None:
        return None
    values = list(value)
    if len(values) != 3:
        raise EditError('expected a 3-element vector, got %r' % (value,))
    return (float(values[0]), float(values[1]), float(values[2]))


def _dataclass_fields(instance):
    """Return the dataclass field values of ``instance`` as a plain dict."""
    return {
        f.name: getattr(instance, f.name)
        for f in instance.__dataclass_fields__.values()}


__all__ = [
    'AddJoint',
    'AddLink',
    'EditError',
    'EditOperation',
    'Rename',
    'RemoveJoint',
    'RemoveLink',
    'SetJointAxis',
    'SetJointLimit',
    'UpdateJoint',
    'apply_operations',
    'operation_from_dict',
    'operations_from_dicts',
]
