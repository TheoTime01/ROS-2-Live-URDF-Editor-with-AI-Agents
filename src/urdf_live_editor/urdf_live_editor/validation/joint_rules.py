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
Per-joint-type validation rules for URDF models.

Encodes the constraints URDF places on each joint type:

* ``revolute`` / ``prismatic`` — need a non-degenerate axis, finite
  ``lower``/``upper`` limits with ``lower <= upper``, and positive ``effort``
  and ``velocity``.
* ``continuous`` — needs a non-degenerate axis; it is unbounded, so
  ``lower``/``upper`` are meaningless and a positive ``effort``/``velocity``
  pair is recommended (warned, not required).
* ``fixed`` — must not move: an axis or limit on it is ignored (warned).
* ``floating`` / ``planar`` — accepted as known types with no further checks.

Everything reported here is deterministic; nothing depends on an AI layer.
"""

import math

from urdf_live_editor.validation.result import ValidationResult

KNOWN_TYPES = frozenset((
    'revolute', 'continuous', 'prismatic', 'fixed', 'floating', 'planar'))
_AXIS_TYPES = frozenset(('revolute', 'continuous', 'prismatic'))
_BOUNDED_TYPES = frozenset(('revolute', 'prismatic'))


def check(model):
    """Validate every joint in ``model`` against its per-type rules."""
    result = ValidationResult.ok()
    for joint in model.joints.values():
        _check_joint(joint, result)
    return result


def _check_joint(joint, result):
    """Validate a single joint according to its declared type."""
    jtype = joint.joint_type
    if not jtype:
        return
    if jtype not in KNOWN_TYPES:
        result.add_error(
            'JOINT_UNKNOWN_TYPE',
            "unknown joint type '%s'" % jtype, subject=joint.name)
        return
    if jtype in _AXIS_TYPES:
        _check_axis(joint, result)
    if jtype in _BOUNDED_TYPES:
        _check_bounded_limits(joint, result)
    elif jtype == 'continuous':
        _check_continuous_limits(joint, result)
    elif jtype == 'fixed':
        _check_fixed(joint, result)


def _check_axis(joint, result):
    """Require a present, finite, non-zero axis on a movable joint."""
    axis = joint.axis
    if axis is None:
        result.add_error(
            'JOINT_MISSING_AXIS',
            'movable joint has no axis', subject=joint.name)
        return
    if any(not math.isfinite(component) for component in axis):
        result.add_error(
            'JOINT_NONFINITE_AXIS',
            'joint axis has a non-finite component', subject=joint.name)
        return
    if all(component == 0.0 for component in axis):
        result.add_error(
            'JOINT_ZERO_AXIS',
            'joint axis is the zero vector', subject=joint.name)


def _check_bounded_limits(joint, result):
    """Require finite ordered limits and positive effort/velocity."""
    limit = joint.limit
    if limit is None:
        result.add_error(
            'JOINT_MISSING_LIMIT',
            'bounded joint has no <limit> element', subject=joint.name)
        return
    _check_bound_pair(joint, limit, result)
    _check_effort_velocity(joint, limit, result)


def _check_bound_pair(joint, limit, result):
    """Check that ``lower``/``upper`` are present, finite, and ordered."""
    for name in ('lower', 'upper'):
        value = getattr(limit, name)
        if value is None:
            result.add_error(
                'JOINT_MISSING_LIMIT',
                "bounded joint has no '%s' limit" % name, subject=joint.name)
        elif not math.isfinite(value):
            result.add_error(
                'JOINT_NONFINITE_LIMIT',
                "joint '%s' limit is not finite" % name, subject=joint.name)
    lower, upper = limit.lower, limit.upper
    if (lower is not None and upper is not None
            and math.isfinite(lower) and math.isfinite(upper)
            and lower > upper):
        result.add_error(
            'JOINT_LIMIT_INVERTED',
            'joint lower limit exceeds its upper limit', subject=joint.name)


def _check_effort_velocity(joint, limit, result):
    """Require positive ``effort`` and ``velocity`` on a bounded joint."""
    for name, code in (
            ('effort', 'JOINT_EFFORT'), ('velocity', 'JOINT_VELOCITY')):
        value = getattr(limit, name)
        if value is None:
            result.add_error(
                code + '_MISSING',
                'bounded joint has no %s limit' % name, subject=joint.name)
        elif not math.isfinite(value) or value <= 0.0:
            result.add_error(
                code + '_NONPOSITIVE',
                'joint %s limit must be positive' % name, subject=joint.name)


def _check_continuous_limits(joint, result):
    """Warn about bounds on, and missing effort/velocity of, a spinner."""
    limit = joint.limit
    if limit is None:
        result.add_warning(
            'JOINT_CONTINUOUS_NO_LIMIT',
            'continuous joint has no effort/velocity limit', subject=joint.name)
        return
    if limit.lower is not None or limit.upper is not None:
        result.add_warning(
            'JOINT_CONTINUOUS_BOUNDED',
            'continuous joint declares lower/upper limits, which are ignored',
            subject=joint.name)
    for name in ('effort', 'velocity'):
        value = getattr(limit, name)
        if value is None:
            result.add_warning(
                'JOINT_CONTINUOUS_NO_LIMIT',
                'continuous joint has no %s limit' % name, subject=joint.name)
        elif not math.isfinite(value) or value <= 0.0:
            result.add_error(
                'JOINT_%s_NONPOSITIVE' % name.upper(),
                'joint %s limit must be positive' % name, subject=joint.name)


def _check_fixed(joint, result):
    """Warn when a fixed joint carries motion attributes that are ignored."""
    if joint.axis is not None:
        result.add_warning(
            'JOINT_FIXED_HAS_AXIS',
            'fixed joint declares an axis, which is ignored',
            subject=joint.name)
    if joint.limit is not None and not joint.limit.is_empty():
        result.add_warning(
            'JOINT_FIXED_HAS_LIMIT',
            'fixed joint declares a limit, which is ignored',
            subject=joint.name)
