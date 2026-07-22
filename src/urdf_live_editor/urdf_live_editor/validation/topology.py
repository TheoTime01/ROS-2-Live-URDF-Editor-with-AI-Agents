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
Topology validation for URDF models.

A valid URDF is a single kinematic tree: exactly one root link, every other
link reached by exactly one joint, and no cycles or disconnected components.
This module builds the link graph from the joints and reports each way the
graph departs from that shape. It only follows joints whose parent and child
are both declared links, so it composes cleanly with the schema check that
reports the dangling references themselves.
"""

from urdf_live_editor.validation.result import ValidationResult


def check(model):
    """Validate that ``model`` forms a single connected acyclic tree."""
    result = ValidationResult.ok()
    if not model.links:
        return result.add_error(
            'TOPO_NO_LINKS', 'model declares no links')

    children, child_of = _build_graph(model, result)
    roots = [name for name in model.link_names() if name not in child_of]

    if not roots:
        result.add_error(
            'TOPO_NO_ROOT',
            'every link has a parent joint; the graph has no root '
            '(it contains a cycle)')
        return result
    if len(roots) > 1:
        result.add_error(
            'TOPO_MULTIPLE_ROOTS',
            'expected exactly one root link, found %d: %s'
            % (len(roots), ', '.join(sorted(roots))))

    reached = _reachable(roots, children)
    _check_cycles(roots, children, result)
    _check_disconnected(model, reached, result)
    return result


def _build_graph(model, result):
    """Return ``(children, child_of)`` maps, flagging multi-parent links."""
    children = {name: [] for name in model.links}
    child_of = {}
    for joint in model.joints.values():
        parent, child = joint.parent, joint.child
        if parent not in model.links or child not in model.links:
            continue
        children[parent].append(child)
        if child in child_of:
            result.add_error(
                'TOPO_MULTIPLE_PARENTS',
                "link '%s' is the child of more than one joint" % child,
                subject=child)
        else:
            child_of[child] = parent
    return children, child_of


def _reachable(roots, children):
    """Return the set of links reachable from ``roots`` (cycle-safe)."""
    reached = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node in reached:
            continue
        reached.add(node)
        stack.extend(children.get(node, ()))
    return reached


def _check_cycles(roots, children, result):
    """Flag any cycle reachable from ``roots`` via depth-first search."""
    color = {}
    for root in roots:
        stack = [(root, iter(children.get(root, ())))]
        color[root] = 1
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if color.get(nxt) == 1:
                    result.add_error(
                        'TOPO_CYCLE',
                        "cycle detected through link '%s'" % nxt,
                        subject=nxt)
                elif color.get(nxt) is None:
                    color[nxt] = 1
                    stack.append((nxt, iter(children.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = 2
                stack.pop()


def _check_disconnected(model, reached, result):
    """Flag links not reachable from the root (cyclic or islanded)."""
    for name in model.link_names():
        if name not in reached:
            result.add_error(
                'TOPO_DISCONNECTED',
                "link '%s' is not connected to the root" % name,
                subject=name)
