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
Deterministic knowledge base behind the explanation and repair agents.

The Constraint Validator and Kinematic Reasoning agents turn machine
:class:`~urdf_live_editor.validation.result.ValidationIssue` codes into
human-readable prose, and the Repair Agent proposes concrete edit operations to
fix a broken model. Both jobs are grounded here in a fixed table rather than in
free-form model output, so the AI layer's diagnoses and repairs are reproducible
in CI without any API call. A live agent still narrates in its own words; this
module gives it (and the deterministic tests) a trustworthy substrate.
"""

import math

# Defaults the repair agent fills in when a value is missing or degenerate.
DEFAULT_AXIS = [0.0, 0.0, 1.0]
DEFAULT_LOWER = -1.5708
DEFAULT_UPPER = 1.5708
DEFAULT_EFFORT = 10.0
DEFAULT_VELOCITY = 1.0

_AXIS_CODES = frozenset((
    'JOINT_MISSING_AXIS', 'JOINT_ZERO_AXIS', 'JOINT_NONFINITE_AXIS'))
_LIMIT_CODES = frozenset((
    'JOINT_MISSING_LIMIT', 'JOINT_NONFINITE_LIMIT', 'JOINT_LIMIT_INVERTED',
    'JOINT_EFFORT_MISSING', 'JOINT_EFFORT_NONPOSITIVE',
    'JOINT_VELOCITY_MISSING', 'JOINT_VELOCITY_NONPOSITIVE'))

# code -> (plain-language explanation, how a repair would address it)
_ISSUE_KB = {
    'SCHEMA_MALFORMED_XML': (
        'The document is not well-formed XML, so nothing downstream can parse '
        'it.',
        'Fix the XML syntax by hand; a structural edit cannot be staged until '
        'the text parses.'),
    'SCHEMA_ROOT_NOT_ROBOT': (
        'A URDF document must be rooted at a <robot> element.',
        'Wrap the links and joints in a single <robot> element.'),
    'SCHEMA_LINK_MISSING_NAME': (
        'Every link needs a unique name; one link has none.',
        'Give the link a name attribute.'),
    'SCHEMA_JOINT_MISSING_NAME': (
        'Every joint needs a unique name; one joint has none.',
        'Give the joint a name attribute.'),
    'SCHEMA_DUPLICATE_LINK': (
        'Two links share a name, so references to it are ambiguous.',
        'Rename one of the colliding links.'),
    'SCHEMA_DUPLICATE_JOINT': (
        'Two joints share a name, so references to it are ambiguous.',
        'Rename one of the colliding joints.'),
    'SCHEMA_JOINT_MISSING_TYPE': (
        'A joint has no type, so its motion is undefined.',
        'Set the joint type (revolute, continuous, prismatic, or fixed).'),
    'SCHEMA_JOINT_MISSING_PARENT': (
        'A joint declares no parent link.',
        'Point the joint at an existing parent link.'),
    'SCHEMA_JOINT_MISSING_CHILD': (
        'A joint declares no child link.',
        'Point the joint at an existing child link.'),
    'SCHEMA_JOINT_UNKNOWN_PARENT': (
        'A joint names a parent link that is not declared in the model.',
        'Add the missing link, or repoint the joint at an existing one.'),
    'SCHEMA_JOINT_UNKNOWN_CHILD': (
        'A joint names a child link that is not declared in the model.',
        'Add the missing link, or repoint the joint at an existing one.'),
    'SCHEMA_JOINT_SELF_LOOP': (
        'A joint connects a link to itself, which is not a real degree of '
        'freedom.',
        'Repoint one endpoint at a different link.'),
    'TOPO_NO_LINKS': (
        'The model has no links, so there is nothing to visualize or move.',
        'Add at least one link.'),
    'TOPO_NO_ROOT': (
        'Every link has a parent joint, so the kinematic graph has no base to '
        'anchor to; this happens when the joints form a cycle.',
        'Break the cycle so exactly one link is left without a parent joint.'),
    'TOPO_MULTIPLE_ROOTS': (
        'A URDF must be a single tree with one base link, but several links '
        'have no parent joint.',
        'Connect the extra roots into the tree, or remove them.'),
    'TOPO_MULTIPLE_PARENTS': (
        'A link is the child of more than one joint; in a tree each link has '
        'exactly one parent.',
        'Remove or repoint the extra joint so the link has a single parent.'),
    'TOPO_CYCLE': (
        'The joints form a closed loop; a URDF kinematic tree cannot contain '
        'cycles.',
        'Remove one joint from the loop to reopen the tree.'),
    'TOPO_DISCONNECTED': (
        'A link cannot be reached from the base through the joints, so it '
        'would float free of the robot.',
        'Add a joint connecting the island to the tree.'),
    'JOINT_UNKNOWN_TYPE': (
        'The joint declares a type URDF does not recognize.',
        'Change it to a known type (revolute, continuous, prismatic, fixed, '
        'floating, or planar).'),
    'JOINT_MISSING_AXIS': (
        'A revolute, continuous, or prismatic joint moves along an axis, and '
        'this one declares none.',
        'Set an axis, e.g. [0, 0, 1].'),
    'JOINT_ZERO_AXIS': (
        'The joint axis is the zero vector, which defines no direction of '
        'motion.',
        'Set a non-zero axis, e.g. [0, 0, 1].'),
    'JOINT_NONFINITE_AXIS': (
        'The joint axis has a non-finite (inf/NaN) component.',
        'Set a finite axis, e.g. [0, 0, 1].'),
    'JOINT_MISSING_LIMIT': (
        'A bounded joint (revolute or prismatic) needs finite lower/upper '
        'limits and this one is missing them.',
        'Add lower and upper limits (plus effort and velocity).'),
    'JOINT_NONFINITE_LIMIT': (
        'A joint limit is not finite, so the range of motion is undefined.',
        'Replace it with a finite value.'),
    'JOINT_LIMIT_INVERTED': (
        'The lower limit exceeds the upper limit, so the joint has an empty '
        'range of motion.',
        'Swap the limits so lower <= upper.'),
    'JOINT_EFFORT_MISSING': (
        'A bounded joint needs a positive effort limit and this one has none.',
        'Add a positive effort limit.'),
    'JOINT_EFFORT_NONPOSITIVE': (
        'The effort limit must be positive; a zero or negative effort lets the '
        'joint exert no force.',
        'Set a positive effort limit.'),
    'JOINT_VELOCITY_MISSING': (
        'A bounded joint needs a positive velocity limit and this one has '
        'none.',
        'Add a positive velocity limit.'),
    'JOINT_VELOCITY_NONPOSITIVE': (
        'The velocity limit must be positive; a zero or negative velocity '
        'freezes the joint.',
        'Set a positive velocity limit.'),
}

_TYPE_SEMANTICS = {
    'revolute': (
        'A revolute joint rotates about its axis between a lower and an upper '
        'limit.'),
    'continuous': (
        'A continuous joint spins freely about its axis with no limit; any '
        'lower/upper bounds are ignored.'),
    'prismatic': (
        'A prismatic joint slides along its axis between a lower and an upper '
        'limit.'),
    'fixed': (
        'A fixed joint rigidly welds child to parent; it has no axis, limit, '
        'or degree of freedom.'),
    'floating': (
        'A floating joint allows all six degrees of freedom between the '
        'links.'),
    'planar': (
        'A planar joint allows motion in the plane orthogonal to its axis.'),
}

_MOVABLE_TYPES = frozenset(('revolute', 'continuous', 'prismatic'))


def explain_code(code):
    """Return ``(explanation, repair_hint)`` for a validation ``code``."""
    return _ISSUE_KB.get(
        code,
        ('No detailed explanation is registered for this issue.',
         'Inspect the model and correct the reported subject.'))


def explain_issue(issue):
    """Return a JSON-serializable, human-readable view of one issue."""
    explanation, repair_hint = explain_code(issue.code)
    return {
        'code': issue.code,
        'severity': issue.severity.value,
        'subject': issue.subject,
        'message': issue.message,
        'explanation': explanation,
        'repair_hint': repair_hint,
    }


def explain_result(result):
    """Return the explained view of every issue in a validation result."""
    return [explain_issue(issue) for issue in result]


def describe_joint_report(joint, issues):
    """Return a structured description of ``joint`` and its ``issues``."""
    semantics = _TYPE_SEMANTICS.get(
        joint.joint_type, 'Unrecognized joint type.')
    return {
        'name': joint.name,
        'type': joint.joint_type,
        'parent': joint.parent,
        'child': joint.child,
        'axis': list(joint.axis) if joint.axis is not None else None,
        'origin_xyz': (
            list(joint.origin_xyz) if joint.origin_xyz is not None else None),
        'origin_rpy': (
            list(joint.origin_rpy) if joint.origin_rpy is not None else None),
        'limit': _limit_dict(joint.limit),
        'semantics': semantics,
        'movable': joint.joint_type in _MOVABLE_TYPES,
        'issues': [explain_issue(issue) for issue in issues],
    }


def describe_degeneracies(model):
    """
    Return human-readable notes on kinematic degeneracies in ``model``.

    These are the observations the Kinematic Reasoning agent surfaces: motion
    attributes that have no effect, bounds that are ignored, degenerate axes,
    and the overall count of actuated degrees of freedom.
    """
    notes = []
    dof = 0
    for joint in model.joints.values():
        jtype = joint.joint_type
        if jtype in _MOVABLE_TYPES:
            dof += 1
        if jtype == 'fixed' and (
                joint.axis is not None
                or (joint.limit is not None and not joint.limit.is_empty())):
            notes.append(
                "fixed joint '%s' declares motion attributes that have no "
                'kinematic effect' % joint.name)
        if jtype == 'continuous' and joint.limit is not None and (
                joint.limit.lower is not None or joint.limit.upper is not None):
            notes.append(
                "continuous joint '%s' declares lower/upper bounds, but a "
                'continuous joint spins freely and ignores them' % joint.name)
        if jtype in _MOVABLE_TYPES and _axis_is_degenerate(joint.axis):
            notes.append(
                "joint '%s' has a degenerate (zero or missing) axis and cannot "
                'define a direction of motion' % joint.name)
    notes.append(
        'the mechanism has %d actuated degree%s of freedom'
        % (dof, '' if dof == 1 else 's'))
    return notes


def suggest_repairs(model, result):
    """
    Return edit-operation dicts that would fix the errors in ``result``.

    Only errors with a mechanical, unambiguous fix produce an operation:
    degenerate axes get a default axis, and broken limits are rebuilt from the
    joint's surviving values plus sane defaults. Structural problems that need a
    human decision (an unknown parent link, say) are explained by
    :func:`explain_result` but intentionally left without an auto-repair.
    """
    by_subject = {}
    for issue in result.errors:
        if issue.subject is None:
            continue
        by_subject.setdefault(issue.subject, set()).add(issue.code)

    repairs = []
    for name, codes in by_subject.items():
        joint = model.get_joint(name)
        if joint is None:
            continue
        if codes & _AXIS_CODES:
            repairs.append({
                'op': 'set_joint_axis',
                'name': name,
                'axis': list(DEFAULT_AXIS),
            })
        if codes & _LIMIT_CODES:
            repairs.append(_repair_limit(joint))
    return repairs


# -- helpers --------------------------------------------------------------


def _limit_dict(limit):
    """Return a JSON view of a joint limit, or ``None``."""
    if limit is None:
        return None
    return {
        'lower': limit.lower,
        'upper': limit.upper,
        'effort': limit.effort,
        'velocity': limit.velocity,
    }


def _axis_is_degenerate(axis):
    """Return ``True`` when ``axis`` is missing, non-finite, or all zeros."""
    if axis is None:
        return True
    if any(not math.isfinite(component) for component in axis):
        return True
    return all(component == 0.0 for component in axis)


def _positive(value):
    """Return ``True`` when ``value`` is a finite, strictly positive number."""
    return (
        value is not None and math.isfinite(value) and value > 0.0)


def _repair_limit(joint):
    """Build a ``set_joint_limit`` op that fixes ``joint``'s limits."""
    limit = joint.limit
    effort = limit.effort if limit is not None else None
    velocity = limit.velocity if limit is not None else None
    op = {
        'op': 'set_joint_limit',
        'name': joint.name,
        'effort': effort if _positive(effort) else DEFAULT_EFFORT,
        'velocity': velocity if _positive(velocity) else DEFAULT_VELOCITY,
    }
    # continuous joints are unbounded; only revolute/prismatic carry a range.
    if joint.joint_type != 'continuous':
        lower = limit.lower if limit is not None else None
        upper = limit.upper if limit is not None else None
        if lower is None or not math.isfinite(lower):
            lower = DEFAULT_LOWER
        if upper is None or not math.isfinite(upper):
            upper = DEFAULT_UPPER
        if lower > upper:
            lower, upper = upper, lower
        op['lower'] = lower
        op['upper'] = upper
    return op
