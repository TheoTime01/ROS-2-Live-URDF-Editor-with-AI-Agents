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
Declarative specifications for the URDF MCP tools.

Each :class:`ToolSpec` names one tool the agents may call, its human-readable
description, the shape of its arguments, and whether it *mutates* the model.
The same table drives three things: the offline
:class:`~urdf_ai_agents.dispatch.ToolDispatcher`, the mutation guard, and (when
the Claude Agent SDK is installed) the in-process MCP server built in
:mod:`urdf_ai_agents.sdk_adapter`. Keeping the vocabulary in one place is what
lets the deterministic tests and the live SDK path stay in lock-step.
"""

from dataclasses import dataclass, field
from typing import Dict

# The MCP server name the tools are grouped under. The SDK exposes each tool to
# Claude as ``mcp__<SERVER_NAME>__<tool>``; :func:`qualified_name` builds that.
SERVER_NAME = 'urdf'


@dataclass(frozen=True)
class ToolSpec:
    """One MCP tool: its name, description, argument shape, and mutation flag."""

    name: str
    description: str
    input_schema: Dict[str, object] = field(default_factory=dict)
    mutating: bool = False

    def qualified_name(self):
        """Return the ``mcp__<server>__<tool>`` name the SDK exposes."""
        return qualified_name(self.name)


def qualified_name(tool_name):
    """Return the SDK-qualified name for ``tool_name``."""
    return 'mcp__%s__%s' % (SERVER_NAME, tool_name)


TOOL_SPECS = (
    ToolSpec(
        'read_urdf',
        'Return the current robot_description as URDF, its version index, and '
        'its validation verdict. Read-only.',
        {},
        mutating=False),
    ToolSpec(
        'describe_joint',
        'Describe one joint: its type, parent/child links, axis, limits, the '
        'kinematic meaning of that type, and any validation issues touching '
        'it. Read-only.',
        {'name': str},
        mutating=False),
    ToolSpec(
        'validate_model',
        'Validate raw URDF (pass "urdf"), a staged candidate (pass '
        '"operations"), or the current model (pass neither). Read-only; never '
        'commits.',
        {'urdf': str, 'operations': list},
        mutating=False),
    ToolSpec(
        'stage_edit',
        'Apply a list of EditOperation objects to a candidate copy and '
        'validate it, without committing. Must be called before apply_model.',
        {'operations': list},
        mutating=False),
    ToolSpec(
        'apply_model',
        'Commit a previously staged, valid candidate as a new version. The '
        'operations must match the last stage_edit exactly.',
        {'operations': list, 'label': str},
        mutating=True),
    ToolSpec(
        'rollback',
        'Restore an earlier committed version by index, appending it as the '
        'new current version.',
        {'target_index': int},
        mutating=True),
)

SPEC_BY_NAME = {spec.name: spec for spec in TOOL_SPECS}

TOOL_NAMES = tuple(spec.name for spec in TOOL_SPECS)


def allowed_tool_names():
    """Return the SDK-qualified names of every tool, for ``allowed_tools``."""
    return [spec.qualified_name() for spec in TOOL_SPECS]
